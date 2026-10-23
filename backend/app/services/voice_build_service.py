"""Voice profiles from all of a character's lines (voice pipeline, Pass 2).

Replaces the window-by-window extraction in ``voice_service`` (kept until
the voice-redesign cleanup for comparison). Reads the lines Pass 1 stored
in ``dialogue_lines``, makes one call per character (or per group of
characters with few lines, ``voice_profiles.plan_units``), several at
once, and stores each profile with its cited evidence and its reference
passages. The passages are then translated as before
(``voice_service.run_translation_for_voices``).

A new run keeps profiles the author accepted, adjusted or rejected and
rebuilds the proposed ones. A run resumes by skipping characters that
already have a profile. The book's ``voice_extraction_windows_*`` columns
count profile calls.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langfuse import propagate_attributes
from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.generation.chains.build_voice_profile_chain import build_voice_profiles
from app.generation.client import GenerationDisabledError
from app.generation.usage import counting
from app.models.book import Book, Chapter, Paragraph
from app.models.glossary import INACTIVE_STATUSES, GlossaryEntry
from app.models.speakers import DialogueLine
from app.models.voice import CharacterVoice, VoiceNotepad, VoiceSelectedPassage
from app.services import voice_service
from app.services.cost_guard import CostGuard, save_state, start_guard
from app.services.glossary_extraction_estimate import glossary_window_count
from app.services.speaker_chunks import windows_for_span
from app.services.stages import glossary_ready
from app.services.voice_extraction_estimate import profile_calls_cost
from app.services.voice_profiles import (
    MIN_LINES,
    CharacterLines,
    SpokenLine,
    ValidatedProfile,
    cut_passage,
    plan_units,
    render_unit,
    sample_lines,
    validate_profiles,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)

# Statuses a new run leaves alone (decision 4 in the redesign doc).
_KEPT_STATUSES = ("accepted", "adjusted", "rejected")


# ─── Loading ────────────────────────────────────────────


@dataclass(slots=True)
class BookLines:
    characters: list[CharacterLines]
    chapter_paragraphs: dict[UUID, list[tuple[UUID, str]]]
    total_windows: int


async def load_book_lines(session: AsyncSession, *, book_id: UUID) -> BookLines:
    """Speech and thought lines of every active glossary character, in book order."""
    speaker = aliased(GlossaryEntry)
    addressee = aliased(GlossaryEntry)
    rows = (
        await session.execute(
            select(
                DialogueLine,
                Paragraph.text,
                Chapter.id,
                Chapter.position,
                speaker.id,
                speaker.canonical_form,
                addressee.canonical_form,
            )
            .join(Paragraph, Paragraph.id == DialogueLine.paragraph_id)
            .join(Chapter, Chapter.id == Paragraph.chapter_id)
            .join(speaker, speaker.id == DialogueLine.speaker_glossary_entry_id)
            .outerjoin(addressee, addressee.id == DialogueLine.addressee_glossary_entry_id)
            .where(
                DialogueLine.book_id == book_id,
                DialogueLine.kind.in_(("speech", "thought")),
                speaker.term_type == "character_name",
                speaker.status.not_in(INACTIVE_STATUSES),
            )
            .order_by(DialogueLine.line_index)
        )
    ).all()
    by_id: dict[UUID, CharacterLines] = {}
    chapter_ids: set[UUID] = set()
    for dl, text, chapter_id, position, gid, name, to in rows:
        ch = by_id.setdefault(gid, CharacterLines(glossary_entry_id=gid, name=name))
        line = SpokenLine(
            paragraph_id=dl.paragraph_id,
            line_index=dl.line_index,
            chapter_id=chapter_id,
            chapter_number=position + 1,
            kind=dl.kind,
            text=text.strip(),
            addressee=to,
            inferred=dl.confidence == "inferred",
            word_offset=dl.word_offset,
        )
        (ch.speech if dl.kind == "speech" else ch.thoughts).append(line)
        chapter_ids.add(chapter_id)

    paragraphs: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
    if chapter_ids:
        prow = await session.execute(
            select(Paragraph.chapter_id, Paragraph.id, Paragraph.text)
            .where(Paragraph.chapter_id.in_(chapter_ids))
            .order_by(Paragraph.chapter_id, Paragraph.position)
        )
        for chapter_id, pid, text in prow.all():
            if (text or "").strip():
                paragraphs[chapter_id].append((pid, text))

    counts = voice_service.compute_passage_counts(
        occurrence_counts={c.glossary_entry_id: len(c.speech) for c in by_id.values() if c.speech}
    )
    for c in by_id.values():
        c.passage_count = max(1, min(counts.get(c.glossary_entry_id, 1), 4, len(c.speech) or 1))

    book = await session.get(Book, book_id)
    total_windows = glossary_window_count(
        book.word_count if book is not None else 0,
        window_words=VOICE_EXTRACTION_WINDOW_WORDS,
        overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
    )
    return BookLines(list(by_id.values()), dict(paragraphs), total_windows)


async def _profiled_ids(session: AsyncSession, *, book_id: UUID) -> set[UUID]:
    rows = await session.execute(
        select(CharacterVoice.glossary_entry_id).where(CharacterVoice.book_id == book_id)
    )
    return {r[0] for r in rows.all()}


def _pending_units(lines: BookLines, done: set[UUID]) -> list[list[CharacterLines]]:
    units = plan_units(lines.characters)
    out = []
    for unit in units:
        left = [c for c in unit if c.glossary_entry_id not in done]
        if left:
            out.append(left)
    return out


def unit_tokens(unit: list[CharacterLines]) -> int:
    """Line tokens one call sends (after sampling)."""
    total = 0
    for c in unit:
        sent, _ = sample_lines(c.speech)
        total += sum(ln.tokens for ln in sent) + sum(ln.tokens for ln in c.thoughts)
    return total


async def profile_estimate_inputs(
    session: AsyncSession, *, book_id: UUID
) -> tuple[list[int], int] | None:
    """``(line tokens per call, speaking characters)`` once Pass 1 has lines."""
    lines = await load_book_lines(session, book_id=book_id)
    units = plan_units(lines.characters)
    if not units:
        return None
    return [unit_tokens(u) for u in units], sum(len(u) for u in units)


# ─── Preconditions ──────────────────────────────────────


async def can_run(session: AsyncSession, *, book_id: UUID) -> tuple[bool, str | None]:
    book = await session.get(Book, book_id)
    if book is None:
        return (False, "Book not found.")
    if book.glossary_extraction_status == "running":
        return (False, "Wait for glossary extraction to finish.")
    if not glossary_ready(book):
        return (False, "Run glossary extraction first.")
    if book.speakers_extraction_status != "completed":
        return (False, "Run Pass 1 (speaker identification) to the end first.")
    n = await session.scalar(
        select(func.count())
        .select_from(DialogueLine)
        .where(
            DialogueLine.book_id == book_id,
            DialogueLine.speaker_glossary_entry_id.is_not(None),
        )
    )
    if not n:
        return (False, "Pass 1 found no lines with a speaker; re-run Pass 1.")
    return (True, None)


async def can_continue(session: AsyncSession, *, book_id: UUID) -> bool:
    """True when a stopped or failed run still has characters without a profile."""
    book = await session.get(Book, book_id)
    if book is None or book.voice_extraction_status not in ("failed", "cancelled"):
        return False
    if book.voice_extraction_windows_total is None:
        return False
    lines = await load_book_lines(session, book_id=book_id)
    done = await _profiled_ids(session, book_id=book_id)
    return bool(_pending_units(lines, done))


# ─── Storing ────────────────────────────────────────────


def _evidence(p: ValidatedProfile, *, sampled_lines: int | None) -> dict[str, Any]:
    return {
        "features": [
            {"feature": f, "paragraph_ids": [str(x) for x in ids]} for f, ids in p.features
        ],
        "register_shifts": [
            {"situation": s, "change": c, "paragraph_ids": [str(x) for x in ids]}
            for s, c, ids in p.shifts
        ],
        "lines_sent": sampled_lines if sampled_lines is not None else len(p.character.speech),
        "sampled": sampled_lines is not None,
    }


async def store_profile(
    session: AsyncSession,
    *,
    book_id: UUID,
    profile: ValidatedProfile,
    lines: BookLines,
    sampled_lines: int | None,
) -> UUID:
    """Insert one profile and its passages. Caller commits."""
    ch = profile.character
    first, last = ch.speech[0], ch.speech[-1]
    first_windows = windows_for_span(first.word_offset, 1, total_windows=lines.total_windows)
    last_windows = windows_for_span(last.word_offset, 1, total_windows=lines.total_windows)
    voice = CharacterVoice(
        source_voice_observation=profile.observation,
        target_voice_strategy=profile.strategy,
        first_seen_window=first_windows[0] if first_windows else 0,
        last_observed_window=last_windows[-1] if last_windows else 0,
        status="proposed",
        evidence=_evidence(profile, sampled_lines=sampled_lines),
        line_count=len(ch.speech),
        low_evidence=len(ch.speech) < MIN_LINES,
    )
    voice.book_id = book_id
    voice.glossary_entry_id = ch.glossary_entry_id
    session.add(voice)
    await session.flush()
    for rank, (p_first, p_last, why) in enumerate(profile.passages):
        text, fp, lp = cut_passage(
            p_first, p_last, lines.chapter_paragraphs.get(p_first.chapter_id, [])
        )
        sp = VoiceSelectedPassage(
            source_text=text,
            why_selected=why,
            selection_rank=rank,
            status="proposed",
            first_paragraph_id=fp,
            last_paragraph_id=lp,
        )
        sp.voice_id = voice.id
        session.add(sp)
    return voice.id


# ─── The run ────────────────────────────────────────────


def _expected_cost(total_usd: float, weights: list[int]) -> Callable[[int], float]:
    """Expected spend after ``k`` calls, largest calls first (the run's order)."""
    total = sum(weights)
    cumulative = [0]
    for w in weights:
        cumulative.append(cumulative[-1] + w)

    def expected(k: int) -> float:
        k = max(0, min(k, len(weights)))
        return total_usd * cumulative[k] / total if total else 0.0

    return expected


@dataclass(slots=True)
class _RunState:
    built: list[UUID]
    missing: list[str]
    errors: list[str]
    cancelled: bool = False


async def _run_units(
    *,
    book_id: UUID,
    units: list[list[CharacterLines]],
    lines: BookLines,
    settings: Settings,
    guard: CostGuard | None,
    source_language: str,
    target_language: str,
) -> _RunState:
    """Make the profile calls, ``VOICE_BUILD_CONCURRENCY`` at a time."""
    session_local = get_sessionmaker()
    state = _RunState(built=[], missing=[], errors=[])
    sem = asyncio.Semaphore(max(1, settings.VOICE_BUILD_CONCURRENCY))
    lock = asyncio.Lock()

    async def one(unit: list[CharacterLines]) -> None:
        async with sem:
            async with session_local() as s:
                book = await s.get(Book, book_id)
                if book is None or book.voice_extraction_cancel_requested:
                    state.cancelled = True
                    return
            rendered = render_unit(unit)
            try:
                result = await build_voice_profiles(
                    characters_section=rendered.text,
                    who=rendered.who,
                    has_thoughts=rendered.has_thoughts,
                    source_language=source_language,
                    target_language=target_language,
                    settings=settings,
                )
            except GenerationDisabledError:
                raise
            except Exception as exc:
                log.exception("voice_profile_call_failed", book_id=str(book_id), who=rendered.who)
                state.errors.append(f"{rendered.who}: {str(exc)[:200]}")
                return
            profiles = validate_profiles(result.profiles, rendered)
            got = {p.character.glossary_entry_id for p in profiles}
            state.missing += [c.name for c in unit if c.glossary_entry_id not in got]
            async with lock, session_local() as s:
                for p in profiles:
                    vid = await store_profile(
                        s,
                        book_id=book_id,
                        profile=p,
                        lines=lines,
                        sampled_lines=rendered.sampled.get(p.character.glossary_entry_id),
                    )
                    state.built.append(vid)
                book = await s.get(Book, book_id)
                if book is not None:
                    book.voice_extraction_windows_completed = (
                        book.voice_extraction_windows_completed or 0
                    ) + 1
                    if guard is not None:
                        guard.units_done = book.voice_extraction_windows_completed
                        total = book.voice_extraction_windows_total or 0
                        reason = guard.overrun() if guard.units_done < total else None
                        save_state(book, guard)
                        if reason:
                            book.voice_extraction_cancel_requested = True
                            log.warning(
                                "voice_build_cost_pause", book_id=str(book_id), reason=reason
                            )
                await s.commit()

    await asyncio.gather(*(one(u) for u in units))
    return state


async def _set_failed(book_id: UUID, message: str) -> None:
    async with get_sessionmaker()() as s:
        b = await s.get(Book, book_id)
        if b is not None:
            b.voice_extraction_status = "failed"
            b.voice_extraction_last_error = message[:5000]
            b.voice_extraction_cancel_requested = False
        await s.commit()


async def _finish(book_id: UUID, state: _RunState, settings: Settings) -> None:
    """Translate the new passages, then set the final status."""
    if state.built:
        await voice_service.run_translation_for_voices(
            book_id=book_id, voice_ids=state.built, settings=settings
        )
    if state.cancelled:
        async with get_sessionmaker()() as s:
            await voice_service._finalize_voice_cancelled(s, book_id=book_id)
        return
    problems = []
    if state.errors:
        problems.append(
            f"{len(state.errors)} profile call(s) failed ({'; '.join(state.errors)[:600]})"
        )
    if state.missing:
        problems.append(f"no profile came back for {', '.join(state.missing)}")
    if problems:
        await _set_failed(book_id, "; ".join(problems) + ". Continue retries them.")
        return
    async with get_sessionmaker()() as s:
        b = await s.get(Book, book_id)
        if b is not None:
            b.voice_extraction_status = "completed"
            b.voice_extraction_last_error = None
            b.voice_extraction_cancel_requested = False
            voice_service._clear_voice_progress_fields(b)
        await s.commit()


async def build_book_voices(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
    cost_limit: bool = True,
) -> None:
    """Background task: one profile call per character or group, then passage translation.

    Pauses like Stop when the real cost of the profile calls goes more than
    ``COST_PAUSE_THRESHOLD`` over their estimate, unless ``cost_limit`` is off.
    Calls already started finish; the rest wait for Continue.
    """
    session_local = get_sessionmaker()
    try:
        async with session_local() as session:
            book = await session.get(Book, book_id)
            if book is None:
                return
            if not continue_extraction:
                # Keep what the author reviewed; rebuild the rest.
                await session.execute(
                    delete(CharacterVoice).where(
                        CharacterVoice.book_id == book_id,
                        CharacterVoice.status.not_in(_KEPT_STATUSES),
                    )
                )
                await session.execute(delete(VoiceNotepad).where(VoiceNotepad.book_id == book_id))
                await session.commit()
            lines = await load_book_lines(session, book_id=book_id)
            done = await _profiled_ids(session, book_id=book_id)
            units = _pending_units(lines, done)
            book = await session.get(Book, book_id)
            if book is None:
                return
            if continue_extraction and book.voice_extraction_windows_total:
                total = book.voice_extraction_windows_total
            else:
                total = len(units)
            start = max(0, total - len(units))
            book.voice_extraction_cancel_requested = False
            book.voice_extraction_windows_total = total
            book.voice_extraction_windows_completed = start
            # Expected spend for the calls still to make, after the ones done.
            pending_weights = [unit_tokens(u) for u in units]
            estimate = profile_calls_cost(
                pending_weights, characters=sum(len(u) for u in units), settings=settings
            )
            guard = start_guard(
                book,
                "voices",
                settings=settings,
                expected=_expected_cost(estimate, [0] * start + pending_weights),
                units_total=total,
                start_units=start,
                limit=cost_limit,
                unit_label="call",
            )
            source_language, target_language = book.source_language, book.target_language
            await session.commit()

        with (
            propagate_attributes(session_id=str(book_id), trace_name="voice_profiles"),
            counting(guard.spend),
        ):
            state = await _run_units(
                book_id=book_id,
                units=units,
                lines=lines,
                settings=settings,
                guard=guard,
                source_language=source_language,
                target_language=target_language,
            )
            await _finish(book_id, state, settings)
        async with session_local() as s:
            b = await s.get(Book, book_id)
            if b is not None:
                save_state(b, guard)
            await s.commit()
        log.info(
            "voice_profiles_built",
            book_id=str(book_id),
            profiles=len(state.built),
            errors=len(state.errors),
            missing=len(state.missing),
        )
    except GenerationDisabledError:
        await _set_failed(book_id, "LLM generation disabled (missing API key).")
    except Exception as exc:
        log.exception("voice_profiles_failed", book_id=str(book_id))
        await _set_failed(book_id, str(exc) or type(exc).__name__)


async def can_regenerate(session: AsyncSession, *, book_id: UUID) -> tuple[bool, str | None]:
    ok, reason = await can_run(session, book_id=book_id)
    if not ok:
        return (ok, reason)
    n = await session.scalar(
        select(func.count())
        .select_from(CharacterVoice)
        .where(CharacterVoice.book_id == book_id, CharacterVoice.needs_regeneration.is_(True))
    )
    if not n:
        return (False, "No profiles flagged for regeneration.")
    return (True, None)


async def regenerate_flagged(*, book_id: UUID, settings: Settings) -> None:
    """Rebuild flagged profiles from their stored lines, one call each."""
    session_local = get_sessionmaker()
    try:
        async with session_local() as session:
            book = await session.get(Book, book_id)
            if book is None:
                return
            flagged = set(
                (
                    await session.execute(
                        select(CharacterVoice.glossary_entry_id).where(
                            CharacterVoice.book_id == book_id,
                            CharacterVoice.needs_regeneration.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(
                delete(CharacterVoice).where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.glossary_entry_id.in_(flagged),
                )
            )
            lines = await load_book_lines(session, book_id=book_id)
            units = [[c] for c in lines.characters if c.glossary_entry_id in flagged and c.speech]
            book.voice_extraction_windows_total = len(units)
            book.voice_extraction_windows_completed = 0
            source_language, target_language = book.source_language, book.target_language
            await session.commit()
        with propagate_attributes(session_id=str(book_id), trace_name="voice_regeneration"):
            state = await _run_units(
                book_id=book_id,
                units=units,
                lines=lines,
                settings=settings,
                guard=None,
                source_language=source_language,
                target_language=target_language,
            )
            await _finish(book_id, state, settings)
    except GenerationDisabledError:
        await _set_failed(book_id, "LLM generation disabled (missing API key).")
    except Exception as exc:
        log.exception("voice_regeneration_failed", book_id=str(book_id))
        await _set_failed(book_id, str(exc) or type(exc).__name__)
