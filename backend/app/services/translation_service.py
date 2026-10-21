"""Fragment translation (Step 5): run orchestration and read model.

Flow
----
1. ``start_translation_run`` splits the book into fragments (once per book),
   creates a ``TranslationRun`` and one ``TranslationRunFragment`` per
   fragment to translate. By default it skips fragments that already have a
   polished translation from an earlier run, so a second click translates
   only what is missing.
2. ``run_translation`` (fire-and-forget task) translates fragments in book
   order with ``TRANSLATION_CONCURRENCY`` workers. Each fragment goes
   through faithful → line_edit → polish; each stage is saved as a
   ``FragmentRendition`` as soon as it finishes, so a stopped or failed run
   can be resumed from the last saved stage.
3. ``build_translation_view`` returns, for every paragraph, the latest text
   of each stage plus translator notes, declared polish edits, QA issues and
   style metrics per chapter.

Inputs to every prompt: the accepted (and adjusted) terms of the latest
glossary run, voice profiles of the characters who speak in the fragment
(from speaker windows, plus a name match), and the text around the fragment.
"""

from __future__ import annotations

import asyncio
import os
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from langfuse import propagate_attributes
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.core.config import get_settings
from app.core.db import get_sessionmaker, rowcount
from app.core.logging import get_logger
from app.generation.chains.translate_fragment_chain import (
    calls_per_fragment,
    line_edit_fragment,
    polish_fragment,
    revise_fragment,
    stage_model,
    translate_fragment_faithful,
    translate_fragment_one_step,
)
from app.generation.prompt_manager.prompts.translate_fragment_prompt import (
    GlossaryRow,
    VoiceRow,
    render_fixed_context,
    render_fragment_context,
)
from app.models.book import Book, Chapter
from app.models.speakers import WindowSpeaker
from app.models.translation import (
    TRANSLATION_STAGES,
    FragmentRendition,
    TranslationFragment,
    TranslationRun,
    TranslationRunFragment,
)
from app.models.voice import CharacterVoice
from app.services.fragmenter import ChapterInput, ParagraphInput, plan_fragments
from app.services.glossary_service import load_working_glossary_for_latest_run
from app.services.translation_cache import RunCaches, delete_leftover_caches
from app.services.translation_qa import (
    DASHES_MAX_PER_1K,
    ELLIPSES_MAX_PER_1K,
    SHE_HE_MAX_PCT,
    StyleMetrics,
    hard_checks,
    rhythm_to_fix,
    sentences_to_fix,
    style_metrics,
)
from app.services.voice_service import _strategy_from_recommendation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)

_PREVIOUS_CONTEXT_WORDS = 250
_NEXT_CONTEXT_WORDS = 150
_MEANING_NOTE_CHARS = 160
_STALE_RUN_ERROR = "The server restarted while this run was in progress. Start it again to resume."


TranslationStageName = Literal["faithful", "line_edit", "polish"]


class TranslationConflictError(RuntimeError):
    """A run is already in progress, or there is nothing to translate."""


# ─── Fragments ───────────────────────────────────────────


async def _load_book_with_text(session: AsyncSession, book_id: UUID) -> Book | None:
    stmt = (
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def ensure_fragments(session: AsyncSession, book: Book) -> list[TranslationFragment]:
    """Return the book's fragments, creating them on first use."""
    existing = (
        (
            await session.execute(
                select(TranslationFragment)
                .where(TranslationFragment.book_id == book.id)
                .order_by(TranslationFragment.position)
            )
        )
        .scalars()
        .all()
    )
    if existing:
        return list(existing)
    chapters = [
        ChapterInput(
            id=c.id,
            paragraphs=[
                ParagraphInput(id=p.id, text=p.text or "")
                for p in sorted(c.paragraphs, key=lambda p: p.position)
            ],
        )
        for c in sorted(book.chapters, key=lambda c: c.position)
    ]
    plans = plan_fragments(chapters)
    rows = [
        TranslationFragment(
            book_id=book.id,
            chapter_id=plan.chapter_id,
            position=i,
            paragraph_ids=plan.paragraph_ids,
            word_count=plan.word_count,
            start_word_offset=plan.start_word_offset,
        )
        for i, plan in enumerate(plans)
    ]
    session.add_all(rows)
    await session.flush()
    log.info("translation_fragments_created", book_id=str(book.id), count=len(rows))
    return rows


# ─── Prompt inputs ───────────────────────────────────────


def _fold(text: str) -> str:
    """Lower case without diacritics (ł has no decomposition, so map it by hand)."""
    decomposed = unicodedata.normalize("NFKD", text.lower().replace("ł", "l"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_form_of(canonical: str, variant: str) -> bool:
    """True when ``variant`` looks like a case form or spelling of ``canonical``.

    Glossary extraction stores more than inflections in ``variants``: aliases,
    descriptions and sometimes a different name altogether ("Vynmor" under
    "Naelori", "adept" under "Elantria"). Translation prompts present variants
    as forms of the term, so a wrong one makes the model rename things. Only
    forms that share each word's stem pass: same number of words, and every
    word pair shares a prefix of at least 3 letters and of all but the last
    3 letters of the shorter word (Miro/Mira, Einardzie/Einard, Hanna/Hania,
    Pyłu/Pyłem).
    """
    a_words, b_words = _fold(canonical).split(), _fold(variant).split()
    if not a_words or len(a_words) != len(b_words) or a_words == b_words:
        return False
    for a, b in zip(a_words, b_words, strict=True):
        common = len(os.path.commonprefix([a, b]))
        if common < max(3, min(len(a), len(b)) - 3):
            return False
    return True


async def load_glossary_rows(
    session: AsyncSession, *, book_id: UUID
) -> tuple[list[GlossaryRow], dict[UUID, GlossaryRow]]:
    """Accepted and adjusted terms of the latest glossary run.

    Returns the rows and a map from glossary entry id to row (used to name
    characters for voice profiles).
    """
    _run, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    rows: list[GlossaryRow] = []
    by_id: dict[UUID, GlossaryRow] = {}
    for e in entries:
        rec = e.translation_recommendation or {}
        target = str(rec.get("proposed_target") or "").strip() or e.canonical_form
        notes_parts = []
        author_notes = rec.get("author_notes")
        if author_notes:
            notes_parts.append(str(author_notes))
        if e.meaning:
            meaning = e.meaning.strip()
            if len(meaning) > _MEANING_NOTE_CHARS:
                meaning = meaning[: _MEANING_NOTE_CHARS - 1].rstrip() + "…"
            notes_parts.append(meaning)
        row = GlossaryRow(
            source=e.canonical_form,
            target=target,
            strategy=_strategy_from_recommendation(rec),
            variants=[v for v in (e.variants or []) if is_form_of(e.canonical_form, v)],
            notes=" ".join(notes_parts) or None,
        )
        by_id[e.id] = row
        if e.status in ("accepted", "adjusted"):
            rows.append(row)
    return rows, by_id


async def load_voice_profiles(
    session: AsyncSession, *, book_id: UUID, glossary_by_id: dict[UUID, GlossaryRow]
) -> dict[UUID, VoiceRow]:
    """Voice profiles that are not rejected, keyed by glossary entry id."""
    voices = (
        (
            await session.execute(
                select(CharacterVoice).where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.status != "rejected",
                )
            )
        )
        .scalars()
        .all()
    )
    out: dict[UUID, VoiceRow] = {}
    for v in voices:
        g = glossary_by_id.get(v.glossary_entry_id)
        name = g.target if g is not None else "Unknown character"
        out[v.glossary_entry_id] = VoiceRow(
            name=name,
            observation=v.source_voice_observation,
            strategy=v.target_voice_strategy,
        )
    return out


async def load_speaker_windows(session: AsyncSession, *, book_id: UUID) -> dict[int, set[UUID]]:
    rows = (
        await session.execute(
            select(WindowSpeaker.window_number, WindowSpeaker.glossary_entry_id).where(
                WindowSpeaker.book_id == book_id
            )
        )
    ).all()
    out: dict[int, set[UUID]] = defaultdict(set)
    for n, gid in rows:
        out[int(n)].add(gid)
    return out


def speakers_for_range(windows: dict[int, set[UUID]], *, start: int, word_count: int) -> set[UUID]:
    """Glossary ids of characters who speak in windows overlapping the range.

    Windows are 1-based and use the voice-extraction geometry.
    """
    stride = VOICE_EXTRACTION_WINDOW_WORDS - VOICE_EXTRACTION_OVERLAP_WORDS
    end = start + max(1, word_count)
    found: set[UUID] = set()
    for n, ids in windows.items():
        w_start = (n - 1) * stride
        w_end = w_start + VOICE_EXTRACTION_WINDOW_WORDS
        if w_start < end and w_end > start:
            found |= ids
    return found


def _mentioned(row: GlossaryRow, text: str) -> bool:
    lowered = text.lower()
    forms = [row.source, *row.variants]
    return any(f and len(f) >= 3 and f.lower() in lowered for f in forms)


def _tail_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[-n:]) if len(words) > n else text


def _head_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[:n]) if len(words) > n else text


# ─── Run lifecycle ───────────────────────────────────────


async def latest_run(session: AsyncSession, *, book_id: UUID) -> TranslationRun | None:
    return (
        (
            await session.execute(
                select(TranslationRun)
                .where(TranslationRun.book_id == book_id)
                .order_by(TranslationRun.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _fragments_with_polish(session: AsyncSession, fragment_ids: list[UUID]) -> set[UUID]:
    if not fragment_ids:
        return set()
    rows = (
        await session.execute(
            select(FragmentRendition.fragment_id).where(
                FragmentRendition.fragment_id.in_(fragment_ids),
                FragmentRendition.stage == "polish",
            )
        )
    ).all()
    return {r[0] for r in rows}


async def start_translation_run(
    session: AsyncSession,
    *,
    book_id: UUID,
    chapter_ids: list[UUID] | None,
    retranslate: bool,
    settings: Settings,
) -> TranslationRun:
    """Create a run. Raises ``LookupError`` or ``TranslationConflictError``."""
    book = await _load_book_with_text(session, book_id)
    if book is None:
        raise LookupError("Book not found")
    current = await latest_run(session, book_id=book_id)
    if current is not None and current.status == "running":
        raise TranslationConflictError("A translation run is already in progress for this book.")

    fragments = await ensure_fragments(session, book)
    wanted = set(chapter_ids) if chapter_ids else None
    selected = [f for f in fragments if wanted is None or f.chapter_id in wanted]
    if not retranslate:
        done = await _fragments_with_polish(session, [f.id for f in selected])
        selected = [f for f in selected if f.id not in done]
    if not selected:
        raise TranslationConflictError(
            "Nothing to translate: the selected chapters already have a polished translation."
        )

    run = TranslationRun(
        book_id=book_id,
        chapter_ids=sorted(wanted) if wanted else None,
        fragments_total=len(selected),
        models=_run_models(settings),
    )
    session.add(run)
    await session.flush()
    session.add_all(TranslationRunFragment(run_id=run.id, fragment_id=f.id) for f in selected)
    await session.commit()
    log.info(
        "translation_run_created",
        book_id=str(book_id),
        run_id=str(run.id),
        fragments=len(selected),
    )
    return run


def _run_models(settings: Settings) -> dict[str, str]:
    """Model per stored stage; in two-step mode the final stage is the revision."""
    if settings.TRANSLATION_STAGE_COUNT == 1:
        return {"polish": stage_model(settings, "line_edit")}
    if settings.TRANSLATION_STAGE_COUNT == 2:
        return {
            "faithful": stage_model(settings, "faithful"),
            "polish": stage_model(settings, "line_edit"),
        }
    return {stage: stage_model(settings, stage) for stage in TRANSLATION_STAGES}


async def request_stop(session: AsyncSession, *, book_id: UUID) -> bool:
    result = await session.execute(
        update(TranslationRun)
        .where(TranslationRun.book_id == book_id, TranslationRun.status == "running")
        .values(cancel_requested=True)
    )
    await session.commit()
    return rowcount(result) > 0


async def reconcile_stale_translation_runs_on_startup() -> None:
    """Mark runs left ``running`` by a dead process as failed, and delete their caches."""
    await delete_leftover_caches(get_settings())
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        result = await session.execute(
            update(TranslationRun)
            .where(TranslationRun.status == "running")
            .values(
                status="failed",
                cancel_requested=False,
                error_message=_STALE_RUN_ERROR,
                completed_at=datetime.now(UTC),
            )
        )
        await session.execute(
            update(TranslationRunFragment)
            .where(TranslationRunFragment.status == "running")
            .values(status="pending")
        )
        await session.commit()
        n = rowcount(result)
    if n:
        log.info("reconciled_stale_translation_runs", count=n)


async def resume_translation_run(session: AsyncSession, *, book_id: UUID) -> TranslationRun:
    """Re-open the latest stopped or failed run; unfinished fragments continue."""
    run = await latest_run(session, book_id=book_id)
    if run is None or run.status in ("running", "completed"):
        raise TranslationConflictError("There is no stopped or failed run to continue.")
    await session.execute(
        update(TranslationRunFragment)
        .where(
            TranslationRunFragment.run_id == run.id,
            TranslationRunFragment.status.in_(("failed", "running")),
        )
        .values(status="pending", error_message=None)
    )
    run.status = "running"
    run.cancel_requested = False
    run.error_message = None
    run.completed_at = None
    run.fragments_failed = 0
    await session.commit()
    return run


# ─── Worker ──────────────────────────────────────────────


def title_paragraph_id(chapter_id: UUID) -> str:
    return f"title:{chapter_id}"


class _BookContext:
    """Everything the workers share for one run (read once at start)."""

    def __init__(
        self,
        *,
        book: Book,
        fragments: list[TranslationFragment],
        glossary: list[GlossaryRow],
        glossary_by_id: dict[UUID, GlossaryRow],
        voices: dict[UUID, VoiceRow],
        speaker_windows: dict[int, set[UUID]],
    ) -> None:
        self.book = book
        self.fragments = fragments
        self.index = {f.id: i for i, f in enumerate(fragments)}
        self.paragraph_text = {p.id: p.text or "" for c in book.chapters for p in c.paragraphs}
        self.chapter_title = {
            c.id: (c.title or f"Chapter {i + 1}")
            for i, c in enumerate(sorted(book.chapters, key=lambda c: c.position))
        }
        # The parser keeps the chapter heading (POV name, number, title,
        # epigraph) in ``Chapter.title``. It is translated with the chapter's
        # first fragment, under the pseudo paragraph id ``title:<chapter id>``.
        self.raw_title = {c.id: (c.title or "").strip() for c in book.chapters}
        self.first_in_chapter: set[UUID] = set()
        seen: set[UUID] = set()
        for f in fragments:
            if f.chapter_id not in seen:
                seen.add(f.chapter_id)
                self.first_in_chapter.add(f.id)
        self.glossary = glossary
        self.glossary_by_id = glossary_by_id
        self.voices = voices
        self.speaker_windows = speaker_windows
        # Set by ``run_translation`` once the fixed context and caches exist.
        self.fixed_context = ""
        self.caches: RunCaches | None = None
        self.settings: Settings | None = None
        # Glossary target words may repeat: they are fixed terms, not style.
        self.glossary_words = {w.strip(".,;:'\"") for row in glossary for w in row.target.split()}
        self.allowed_source_words = {
            w for row in glossary for w in row.target.split() if not w.isascii()
        }

    def cache_for(self, stage: str) -> str | None:
        if self.caches is None or self.settings is None:
            return None
        return self.caches.name_for(stage_model(self.settings, stage))

    def source_pairs(self, fragment: TranslationFragment) -> list[tuple[str, str]]:
        pairs = [(str(pid), self.paragraph_text.get(pid, "")) for pid in fragment.paragraph_ids]
        title = self.raw_title.get(fragment.chapter_id, "")
        if fragment.id in self.first_in_chapter and title:
            pairs.insert(0, (title_paragraph_id(fragment.chapter_id), title))
        return pairs

    def source_text(self, fragment: TranslationFragment) -> str:
        return "\n\n".join(self.paragraph_text.get(pid, "") for pid in fragment.paragraph_ids)

    def neighbour(self, fragment: TranslationFragment, step: int) -> TranslationFragment | None:
        i = self.index[fragment.id] + step
        return self.fragments[i] if 0 <= i < len(self.fragments) else None

    def voices_for(self, fragment: TranslationFragment) -> list[VoiceRow]:
        ids = speakers_for_range(
            self.speaker_windows,
            start=fragment.start_word_offset,
            word_count=fragment.word_count,
        )
        text = self.source_text(fragment)
        for gid, row in self.glossary_by_id.items():
            if gid in self.voices and _mentioned(row, text):
                ids.add(gid)
        return [self.voices[g] for g in ids if g in self.voices]


async def _latest_target_text(
    session: AsyncSession, *, fragment_id: UUID, run_id: UUID
) -> str | None:
    """Latest English for a fragment: this run first, then any earlier run."""
    rows = (
        (
            await session.execute(
                select(FragmentRendition)
                .where(FragmentRendition.fragment_id == fragment_id)
                .order_by(FragmentRendition.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    order = {s: i for i, s in enumerate(TRANSLATION_STAGES)}
    rows = sorted(rows, key=lambda r: (r.run_id == run_id, order.get(r.stage, -1)), reverse=True)
    return "\n\n".join(p.get("text", "") for p in rows[0].paragraphs)


def _metrics_block(
    m: StyleMetrics, *, to_fix: list[str], rhythm: list[str], checks: list[str]
) -> str:
    lines = [
        f"- Narration sentences starting with She/He: {m.she_he_pct}% "
        f"(target ≤ {SHE_HE_MAX_PCT:g}%)",
        f"- Ellipses: {m.ellipses_per_1k} per 1,000 words (target ≤ {ELLIPSES_MAX_PER_1K:g})",
        f"- Em dashes: {m.dashes_per_1k} per 1,000 words (target ≤ {DASHES_MAX_PER_1K:g})",
        f"- Stock phrases: {m.stock_total} (target 0)"
        + (": " + ", ".join(f"/{k}/ {v} times" for k, v in m.stock.items()) if m.stock else ""),
    ]
    over = m.over_target()
    lines.append("Over target: " + "; ".join(over) if over else "All targets met; edit lightly.")
    if to_fix:
        lines.append(
            "\nSentences behind the missed targets:\n" + "\n".join(f"- {t}" for t in to_fix)
        )
    if rhythm:
        lines.append(
            "\nRhythm and repetition (look at each; keep only deliberate effects):\n"
            + "\n".join(f"- {r}" for r in rhythm)
        )
    if checks:
        lines.append(
            "\nProblems found by automatic checks (fix these):\n"
            + "\n".join(f"- {c}" for c in checks)
        )
    return "\n".join(lines)


def _to_short(paragraphs: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, str]]:
    short: list[tuple[str, str]] = []
    mapping: dict[str, str] = {}
    for i, (pid, text) in enumerate(paragraphs, start=1):
        sid = f"p{i}"
        short.append((sid, text))
        mapping[sid] = pid
    return short, mapping


def _remap_ids(items: list[dict[str, Any]], mapping: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        d = dict(item)
        pid = str(d.get("paragraph_id", "")).strip()
        d["paragraph_id"] = mapping.get(pid)
        out.append(d)
    return out


async def _translate_fragment(
    *,
    run_id: UUID,
    run_fragment_id: UUID,
    fragment: TranslationFragment,
    ctx: _BookContext,
    settings: Settings,
) -> bool:
    """Run the remaining stages for one fragment. Returns True on success."""
    session_maker = get_sessionmaker()
    book = ctx.book
    async with session_maker() as session:
        run = await session.get(TranslationRun, run_id)
        if run is None or run.cancel_requested:
            return False
        rf = await session.get(TranslationRunFragment, run_fragment_id)
        if rf is None:
            return False
        rf.status = "running"
        await session.commit()

        existing = {
            r.stage: r
            for r in (
                await session.execute(
                    select(FragmentRendition).where(
                        FragmentRendition.run_id == run_id,
                        FragmentRendition.fragment_id == fragment.id,
                    )
                )
            )
            .scalars()
            .all()
        }

        source_pairs = ctx.source_pairs(fragment)
        source_short, mapping = _to_short(source_pairs)
        reverse = {v: k for k, v in mapping.items()}

        prev = ctx.neighbour(fragment, -1)
        nxt = ctx.neighbour(fragment, 1)
        prev_target = (
            await _latest_target_text(session, fragment_id=prev.id, run_id=run_id)
            if prev is not None
            else None
        )
        context = render_fragment_context(
            chapter_title=ctx.chapter_title.get(fragment.chapter_id, ""),
            voices=ctx.voices_for(fragment),
            previous_source=_tail_words(ctx.source_text(prev), _PREVIOUS_CONTEXT_WORDS)
            if prev is not None
            else "",
            previous_target=_tail_words(prev_target, _PREVIOUS_CONTEXT_WORDS)
            if prev_target
            else "",
            next_source=_head_words(ctx.source_text(nxt), _NEXT_CONTEXT_WORDS)
            if nxt is not None
            else "",
        )
        target_language = "English" if book.target_language == "en" else book.target_language

        def checks_for(short: list[tuple[str, str]]) -> list[str]:
            issues = hard_checks(
                source=source_short,
                target=short,
                source_language=book.source_language,
                allowed_words=ctx.allowed_source_words,
            )
            return [f"[{i.paragraph_id}] {i.detail}" for i in issues]

        def short_from_rendition(r: FragmentRendition) -> list[tuple[str, str]]:
            by_id = {p["paragraph_id"]: p.get("text", "") for p in r.paragraphs}
            return [(reverse[pid], by_id.get(pid, "")) for pid, _ in source_pairs]

        async def save(stage: str, result: Any, extra: dict[str, Any]) -> FragmentRendition:
            out = result.output
            paragraphs = [
                {"paragraph_id": mapping[p.paragraph_id], "text": p.text} for p in out.paragraphs
            ]
            texts = [(p["paragraph_id"], p["text"]) for p in paragraphs]
            issues = hard_checks(
                source=source_pairs,
                target=texts,
                source_language=book.source_language,
                allowed_words=ctx.allowed_source_words,
            )
            notes = {
                "notes": _remap_ids([n.model_dump() for n in out.notes], mapping),
                "qa": [i.to_json() for i in issues],
                "metrics": style_metrics([t for _, t in texts]).to_json(),
                **extra,
            }
            rendition = FragmentRendition(
                run_id=run_id,
                fragment_id=fragment.id,
                stage=stage,
                paragraphs=paragraphs,
                notes=notes,
                model=result.model,
                usage_metadata=result.usage,
            )
            session.add(rendition)
            rf.last_stage = stage
            await session.commit()
            return rendition

        async def cancelled() -> bool:
            await session.refresh(run)
            return bool(run.cancel_requested)

        try:
            if settings.TRANSLATION_STAGE_COUNT == 1 and "polish" not in existing:
                # One-step mode: straight from the source to the final text.
                result = await translate_fragment_one_step(
                    fixed_context=ctx.fixed_context,
                    cached_content=ctx.cache_for("line_edit"),
                    context=context,
                    source=source_short,
                    target_language=target_language,
                    settings=settings,
                )
                existing["polish"] = await save("polish", result, {"one_step": True})

            faithful = existing.get("faithful")
            if faithful is None and "polish" not in existing:
                result = await translate_fragment_faithful(
                    fixed_context=ctx.fixed_context,
                    cached_content=ctx.cache_for("faithful"),
                    context=context,
                    source=source_short,
                    target_language=target_language,
                    settings=settings,
                )
                faithful = await save("faithful", result, {})
            if await cancelled():
                rf.status = "pending"
                await session.commit()
                return False

            if settings.TRANSLATION_STAGE_COUNT == 2:
                # Two-step mode: one revision (line edit + style targets),
                # stored as the final stage.
                if "polish" not in existing:
                    faithful_short = short_from_rendition(faithful)
                    draft_metrics = style_metrics([t for _, t in faithful_short])
                    result = await revise_fragment(
                        fixed_context=ctx.fixed_context,
                        cached_content=ctx.cache_for("line_edit"),
                        context=context,
                        source=source_short,
                        faithful=faithful_short,
                        checks=checks_for(faithful_short),
                        rhythm=rhythm_to_fix(faithful_short, ignore=ctx.glossary_words),
                        metrics_block=_metrics_block(
                            draft_metrics,
                            to_fix=sentences_to_fix(faithful_short, draft_metrics),
                            rhythm=[],
                            checks=[],
                        ),
                        target_language=target_language,
                        settings=settings,
                    )
                    await save("polish", result, {"two_step": True})
                existing["polish"] = existing.get("polish") or faithful

            line_edited = existing.get("line_edit")
            if line_edited is None and "polish" not in existing:
                faithful_short = short_from_rendition(faithful)
                result = await line_edit_fragment(
                    fixed_context=ctx.fixed_context,
                    cached_content=ctx.cache_for("line_edit"),
                    context=context,
                    source=source_short,
                    faithful=faithful_short,
                    checks=checks_for(faithful_short),
                    rhythm=rhythm_to_fix(faithful_short, ignore=ctx.glossary_words),
                    target_language=target_language,
                    settings=settings,
                )
                line_edited = await save("line_edit", result, {})
            if await cancelled():
                rf.status = "pending"
                await session.commit()
                return False

            if "polish" not in existing:
                line_short = short_from_rendition(line_edited)
                metrics = style_metrics([t for _, t in line_short])
                result = await polish_fragment(
                    fixed_context=ctx.fixed_context,
                    cached_content=ctx.cache_for("polish"),
                    context=context,
                    source=source_short,
                    line_edited=line_short,
                    metrics_block=_metrics_block(
                        metrics,
                        to_fix=sentences_to_fix(line_short, metrics),
                        rhythm=rhythm_to_fix(line_short, ignore=ctx.glossary_words),
                        checks=checks_for(line_short),
                    ),
                    target_language=target_language,
                    settings=settings,
                )
                await save(
                    "polish",
                    result,
                    {
                        "declared_edits": _remap_ids(
                            [e.model_dump() for e in result.output.declared_edits], mapping
                        )
                    },
                )
        except Exception as exc:
            log.exception(
                "translation_fragment_failed",
                run_id=str(run_id),
                fragment_id=str(fragment.id),
            )
            await session.rollback()
            rf = await session.get(TranslationRunFragment, run_fragment_id)
            if rf is not None:
                rf.status = "failed"
                rf.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            await session.execute(
                update(TranslationRun)
                .where(TranslationRun.id == run_id)
                .values(fragments_failed=TranslationRun.fragments_failed + 1)
            )
            await session.commit()
            return False

        rf.status = "completed"
        rf.error_message = None
        await session.execute(
            update(TranslationRun)
            .where(TranslationRun.id == run_id)
            .values(fragments_completed=TranslationRun.fragments_completed + 1)
        )
        await session.commit()
        return True


async def run_translation(*, run_id: UUID, settings: Settings) -> None:
    """Translate every pending fragment of a run. Fire-and-forget entry point."""
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        run = await session.get(TranslationRun, run_id)
        if run is None:
            return
        book = await _load_book_with_text(session, run.book_id)
        if book is None:
            return
        fragments = await ensure_fragments(session, book)
        glossary, glossary_by_id = await load_glossary_rows(session, book_id=book.id)
        voices = await load_voice_profiles(session, book_id=book.id, glossary_by_id=glossary_by_id)
        windows = await load_speaker_windows(session, book_id=book.id)
        pending = (
            await session.execute(
                select(TranslationRunFragment.id, TranslationRunFragment.fragment_id).where(
                    TranslationRunFragment.run_id == run_id,
                    TranslationRunFragment.status.in_(("pending", "running")),
                )
            )
        ).all()
        # Completed counter is recomputed so a resumed run shows true progress.
        done_count = len(
            (
                await session.execute(
                    select(TranslationRunFragment.id).where(
                        TranslationRunFragment.run_id == run_id,
                        TranslationRunFragment.status == "completed",
                    )
                )
            ).all()
        )
        run.fragments_completed = done_count
        await session.commit()

    ctx = _BookContext(
        book=book,
        fragments=fragments,
        glossary=glossary,
        glossary_by_id=glossary_by_id,
        voices=voices,
        speaker_windows=windows,
    )
    ctx.settings = settings
    ctx.fixed_context = render_fixed_context(
        book_title=book.title,
        source_language=book.manuscript_language or book.source_language,
        target_language="English" if book.target_language == "en" else book.target_language,
        glossary=glossary,
    )
    fragment_by_id = {f.id: f for f in fragments}
    order = {f.id: f.position for f in fragments}
    jobs = sorted(pending, key=lambda r: order.get(r[1], 0))
    semaphore = asyncio.Semaphore(max(1, settings.TRANSLATION_CONCURRENCY))

    async def worker(run_fragment_id: UUID, fragment_id: UUID) -> None:
        async with semaphore:
            fragment = fragment_by_id.get(fragment_id)
            if fragment is None:
                return
            await _translate_fragment(
                run_id=run_id,
                run_fragment_id=run_fragment_id,
                fragment=fragment,
                ctx=ctx,
                settings=settings,
            )

    ctx.caches = await RunCaches.open(
        settings=settings,
        run_id=run_id,
        fixed_context=ctx.fixed_context,
        models={stage_model(settings, s) for s in calls_per_fragment(settings)},
    )
    try:
        await _run_jobs(run_id=run_id, book=book, jobs=jobs, worker=worker)
    finally:
        # Delete the caches however the run ends, so they stop costing money.
        await ctx.caches.close()


async def _run_jobs(
    *,
    run_id: UUID,
    book: Book,
    jobs: list[Any],
    worker: Any,
) -> None:
    """Run the fragment workers, then record how the run ended."""
    session_maker = get_sessionmaker()
    with propagate_attributes(session_id=str(book.id), trace_name="fragment_translation"):
        try:
            await asyncio.gather(*(worker(rf_id, f_id) for rf_id, f_id in jobs))
        except Exception as exc:
            log.exception("translation_run_failed", run_id=str(run_id))
            async with session_maker() as session:
                run = await session.get(TranslationRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                    run.completed_at = datetime.now(UTC)
                    await session.commit()
            return

    async with session_maker() as session:
        run = await session.get(TranslationRun, run_id)
        if run is None:
            return
        statuses = (
            await session.execute(
                select(TranslationRunFragment.status).where(TranslationRunFragment.run_id == run_id)
            )
        ).all()
        counts: dict[str, int] = defaultdict(int)
        for (s,) in statuses:
            counts[s] += 1
        run.fragments_completed = counts["completed"]
        run.fragments_failed = counts["failed"]
        if run.cancel_requested:
            run.status = "cancelled"
        elif counts["failed"] and not counts["completed"]:
            run.status = "failed"
            run.error_message = "Every fragment failed. See the fragment errors."
        elif counts["failed"]:
            run.status = "failed"
            run.error_message = (
                f"{counts['failed']} of {len(statuses)} fragments failed. "
                "Continue the run to retry them."
            )
        else:
            run.status = "completed"
        run.cancel_requested = False
        run.completed_at = datetime.now(UTC)
        await session.commit()
        log.info(
            "translation_run_finished",
            run_id=str(run_id),
            status=run.status,
            completed=counts["completed"],
            failed=counts["failed"],
        )


# ─── Read model ──────────────────────────────────────────


def current_renditions(
    renditions: Sequence[FragmentRendition],
) -> dict[tuple[UUID, str], FragmentRendition]:
    """The renditions that make up each fragment's current translation.

    For every fragment, one run counts: the latest run that produced a final
    stage, or the latest run at all when none has. Only that run's stages are
    returned, so a two-step translation never shows a line edit left over
    from an older three-step run, and a re-run in progress does not hide the
    previous finished text. ``renditions`` must be sorted by ``created_at``.
    """
    final_run: dict[UUID, UUID] = {}
    any_run: dict[UUID, UUID] = {}
    for r in renditions:
        any_run[r.fragment_id] = r.run_id
        if r.stage == "polish":
            final_run[r.fragment_id] = r.run_id
    out: dict[tuple[UUID, str], FragmentRendition] = {}
    for r in renditions:
        if r.run_id == final_run.get(r.fragment_id, any_run[r.fragment_id]):
            out[(r.fragment_id, r.stage)] = r
    return out


async def build_translation_view(session: AsyncSession, *, book_id: UUID) -> dict[str, Any]:
    """Latest run, plus per-chapter translations of each stage.

    For each fragment, the stages of its current run (``current_renditions``).
    Chapters without any translation are listed with ``fragments: []``.
    """
    run = await latest_run(session, book_id=book_id)
    fragments = (
        (
            await session.execute(
                select(TranslationFragment)
                .where(TranslationFragment.book_id == book_id)
                .order_by(TranslationFragment.position)
            )
        )
        .scalars()
        .all()
    )
    renditions = (
        (
            await session.execute(
                select(FragmentRendition)
                .join(TranslationFragment, TranslationFragment.id == FragmentRendition.fragment_id)
                .where(TranslationFragment.book_id == book_id)
                .order_by(FragmentRendition.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    latest = current_renditions(renditions)

    run_fragment_status: dict[UUID, dict[str, Any]] = {}
    if run is not None:
        for rf in (
            (
                await session.execute(
                    select(TranslationRunFragment).where(TranslationRunFragment.run_id == run.id)
                )
            )
            .scalars()
            .all()
        ):
            run_fragment_status[rf.fragment_id] = {
                "status": rf.status,
                "last_stage": rf.last_stage,
                "error_message": rf.error_message,
            }

    chapters: dict[UUID, dict[str, Any]] = {}
    for f in fragments:
        ch = chapters.setdefault(
            f.chapter_id, {"chapter_id": str(f.chapter_id), "fragments": [], "metrics": {}}
        )
        stages: dict[str, Any] = {}
        for stage in TRANSLATION_STAGES:
            r = latest.get((f.id, stage))
            if r is None:
                continue
            stages[stage] = {
                "paragraphs": r.paragraphs,
                "notes": r.notes.get("notes", []),
                "declared_edits": r.notes.get("declared_edits", []),
                "qa": r.notes.get("qa", []),
                "metrics": r.notes.get("metrics", {}),
                "model": r.model,
                "created_at": r.created_at.isoformat(),
            }
            prev = ch["metrics"].get(stage)
            m = StyleMetrics.from_json(r.notes.get("metrics", {}))
            ch["metrics"][stage] = m if prev is None else prev.merge(m)
        ch["fragments"].append(
            {
                "fragment_id": str(f.id),
                "position": f.position,
                "paragraph_ids": [str(p) for p in f.paragraph_ids],
                "word_count": f.word_count,
                "run_status": run_fragment_status.get(f.id),
                "stages": stages,
            }
        )
    for ch in chapters.values():
        ch["metrics"] = {k: v.to_json() for k, v in ch["metrics"].items()}

    return {
        "run": run_json(run),
        "fragment_count": len(fragments),
        "chapters": list(chapters.values()),
    }


def run_json(run: TranslationRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "status": run.status,
        "cancel_requested": run.cancel_requested,
        "chapter_ids": [str(c) for c in run.chapter_ids] if run.chapter_ids else None,
        "fragments_total": run.fragments_total,
        "fragments_completed": run.fragments_completed,
        "fragments_failed": run.fragments_failed,
        "models": run.models,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
