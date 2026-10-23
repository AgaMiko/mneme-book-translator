"""Voice pipeline service — orchestrates the three-chain workflow.

Three phases, in order:

1. **Voice extraction.** Iterative window-by-window calls to
   ``extract_voices_chain``. When Pass 1 (speaker identification)
   is complete, each window only receives glossary characters who
   speak in that window; windows with no speakers skip the LLM call.
   Builds source_voice_observation and target_voice_strategy per
   character and accumulates a candidate-passage pool (cap 8). NO
   translation.

2. **Passage selection.** After extraction completes, code-side
   percentile math determines how many passages each character gets.
   Then one ``select_passages_chain`` call per character picks that
   many passages from the pool.

3. **Translation.** One ``translate_passage_chain`` call per selected
   passage, with full accepted glossary in context.

This module owns:

- The precondition check (glossary completed, has characters).
- Loading character context for each phase.
- Applying delta operations from the extraction chain (with
  ID+name cross-checks via voice_validation).
- The percentile math for passage counts.
- Calling each chain at the right moment.
- Writing each phase's outputs to the correct tables.
- Status-flag bookkeeping on the book row.

Most functions are stubs (``NotImplementedError``) because the SQL is
deployment-specific. The signatures and docstrings define the contract.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from langfuse import propagate_attributes
from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.core.db import get_sessionmaker, rowcount
from app.core.logging import get_logger
from app.generation.chains.extract_voices_chain import extract_voices_window
from app.generation.chains.select_passages_chain import (
    select_passages_for_character,
)
from app.generation.chains.translate_passage_chain import translate_passage
from app.generation.client import GenerationDisabledError
from app.generation.prompt_manager.models.extract_voices_model import (
    CharacterVoiceCompact,
    GlossaryCharacterRef,
    VoiceNote,
    VoiceUpdate,
)
from app.generation.prompt_manager.models.select_passages_model import (
    CandidateInPool,
    PassageSelection,
)
from app.generation.prompt_manager.models.translate_passage_model import (
    GlossaryTermRef,
    PassageTranslation,
    TranslationStrategy,
)
from app.generation.usage import counting
from app.models.book import Book
from app.models.glossary import INACTIVE_STATUSES, GlossaryEntry
from app.models.voice import (
    CharacterVoice,
    VoiceNotepad,
    VoicePassageCandidate,
    VoiceSelectedPassage,
)
from app.schemas.voice import (
    VoiceSelectedPassageOut,
    VoiceWorkingProfileOut,
    VoiceWorkingProfilePatchIn,
    WorkingVoicesResponse,
)
from app.services import speakers_service, voice_validation
from app.services.cost_guard import linear, save_state, start_guard
from app.services.glossary_service import (
    _load_book_plaintext,
    load_working_glossary_for_latest_run,
)
from app.services.glossary_service import (
    make_windows as glossary_make_windows,
)
from app.services.stages import glossary_ready
from app.services.voice_extraction_estimate import estimate_voice_extraction

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)


def _clear_voice_progress_fields(book: Book) -> None:
    book.voice_extraction_windows_total = None
    book.voice_extraction_windows_completed = None


async def _finalize_voice_cancelled(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> None:
    b = await session.get(Book, book_id)
    if b is not None:
        b.voice_extraction_status = "cancelled"
        b.voice_extraction_cancel_requested = False
    await session.commit()


# ─── Startup housekeeping ──────────────────────────────


_STALE_RUNNING_VOICE_ERROR = (
    "Voice extraction was interrupted (server restarted or deploy). "
    "Use Continue to resume, or Stop/Reset as needed."
)


async def reconcile_stale_voice_runs_on_startup() -> None:
    """End in-flight ``running`` flags left behind when the process died.

    Fire-and-forget voice tasks do not survive restarts, but the ``books`` row
    can still show ``voice_extraction_status == 'running'``, which blocks Run
    and confuses the reader. Mark those books as `failed` so the author can
    use Continue (when implemented) or Reset.
    """
    log = get_logger(__name__)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        result = await session.execute(
            update(Book)
            .where(Book.voice_extraction_status == "running")
            .values(
                voice_extraction_status="failed",
                voice_extraction_cancel_requested=False,
                voice_extraction_last_error=_STALE_RUNNING_VOICE_ERROR,
            )
        )
        await session.commit()
        n = rowcount(result)
    if n:
        log.info("reconciled_stale_voice_runs", count=n)


# ─── Review API: reset and working profiles ─────────────


def _primary_selected_passage(
    passages: list[VoiceSelectedPassage],
) -> VoiceSelectedPassage | None:
    if not passages:
        return None
    return min(passages, key=lambda p: p.selection_rank)


def _character_voice_to_working_out(
    voice: CharacterVoice,
) -> VoiceWorkingProfileOut:
    g = voice.glossary_entry
    if g is None:
        msg = f"CharacterVoice {voice.id} has no glossary entry loaded"
        raise RuntimeError(msg)
    ordered = sorted(list(voice.selected_passages), key=lambda p: (p.selection_rank, p.id))
    selected_out = [
        VoiceSelectedPassageOut(
            id=p.id,
            selection_rank=p.selection_rank,
            source_text=p.source_text,
            why_selected=p.why_selected,
            translation_proposed=p.translation_proposed,
            translation_authoritative=p.translation_authoritative,
            status=p.status,
        )
        for p in ordered
    ]
    primary = ordered[0] if ordered else None
    return VoiceWorkingProfileOut(
        id=voice.id,
        glossary_entry_id=voice.glossary_entry_id,
        canonical_name=g.canonical_form,
        source_voice_observation=voice.source_voice_observation,
        target_voice_strategy=voice.target_voice_strategy,
        reference_passage_source=primary.source_text if primary else "",
        reference_passage_translation_proposed=(primary.translation_proposed or "")
        if primary
        else "",
        reference_passage_translation_authoritative=(
            primary.translation_authoritative if primary else None
        ),
        selected_passages=selected_out,
        status=voice.status,
        needs_regeneration=voice.needs_regeneration,
        dialogue_volume_observed=0,
        first_seen_window=voice.first_seen_window,
        last_observed_window=voice.last_observed_window,
        created_at=voice.created_at,
        updated_at=voice.updated_at,
    )


async def build_working_voices_response(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> WorkingVoicesResponse:
    stmt = (
        select(CharacterVoice)
        .join(GlossaryEntry, GlossaryEntry.id == CharacterVoice.glossary_entry_id)
        .where(CharacterVoice.book_id == book_id)
        .options(
            selectinload(CharacterVoice.glossary_entry),
            selectinload(CharacterVoice.selected_passages),
        )
    )
    result = await session.execute(stmt)
    voices = result.scalars().all()
    entries = [_character_voice_to_working_out(v) for v in voices]
    scene_counts = await speakers_service.speaker_window_counts_by_glossary(
        session, book_id=book_id
    )

    def _scene_count(entry: VoiceWorkingProfileOut) -> int:
        n = scene_counts.get(entry.glossary_entry_id, 0)
        if n > 0:
            return n
        if entry.last_observed_window >= entry.first_seen_window:
            return entry.last_observed_window - entry.first_seen_window + 1
        return 0

    entries.sort(
        key=lambda e: (-_scene_count(e), e.canonical_name.casefold()),
    )
    return WorkingVoicesResponse(entries=entries)


async def patch_working_voice_profile(
    session: AsyncSession,
    *,
    book_id: UUID,
    voice_id: UUID,
    patch: VoiceWorkingProfilePatchIn,
) -> VoiceWorkingProfileOut:
    stmt = (
        select(CharacterVoice)
        .where(
            CharacterVoice.id == voice_id,
            CharacterVoice.book_id == book_id,
        )
        .options(
            selectinload(CharacterVoice.glossary_entry),
            selectinload(CharacterVoice.selected_passages),
        )
    )
    voice = (await session.execute(stmt)).scalar_one_or_none()
    if voice is None:
        raise LookupError("voice")

    primary = _primary_selected_passage(list(voice.selected_passages))

    if patch.accept:
        voice.status = "accepted"
        if primary is not None:
            primary.status = "accepted"
            prop = primary.translation_proposed
            if prop is not None and prop != "":
                primary.translation_authoritative = prop
    elif patch.reject:
        voice.status = "rejected"
        if primary is not None:
            primary.status = "rejected"
            primary.translation_authoritative = None
    else:
        if patch.source_voice_observation is not None:
            voice.source_voice_observation = patch.source_voice_observation
            voice.status = "adjusted"
        if patch.target_voice_strategy is not None:
            voice.target_voice_strategy = patch.target_voice_strategy
            voice.status = "adjusted"
        if patch.reference_passage_translation is not None:
            if primary is None:
                msg = "No selected reference passage to update for this profile."
                raise ValueError(msg)
            primary.translation_authoritative = patch.reference_passage_translation
            primary.status = "adjusted"
        if patch.selected_passage_id is not None:
            passage = next(
                (p for p in voice.selected_passages if p.id == patch.selected_passage_id),
                None,
            )
            if passage is None:
                msg = "Selected passage not found on this profile."
                raise ValueError(msg)
            if patch.selected_passage_translation is not None:
                passage.translation_authoritative = patch.selected_passage_translation
                passage.status = "adjusted"
                voice.status = "adjusted"
        if patch.needs_regeneration is not None:
            voice.needs_regeneration = patch.needs_regeneration
    await session.commit()
    return _character_voice_to_working_out(voice)


async def reset_book_voice_data(
    session: AsyncSession,
    *,
    book: Book,
) -> None:
    await session.execute(delete(VoiceNotepad).where(VoiceNotepad.book_id == book.id))
    await session.execute(delete(CharacterVoice).where(CharacterVoice.book_id == book.id))
    book.voice_extraction_status = "idle"
    book.voice_extraction_cancel_requested = False
    book.voice_extraction_windows_total = None
    book.voice_extraction_windows_completed = None
    book.voice_extraction_last_error = None
    await session.commit()


# ─── Precondition ───────────────────────────────────────


async def can_run_voice_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> tuple[bool, str | None]:
    """Check whether voice extraction can proceed for this book.

    Returns ``(True, None)`` if the glossary is usable (finished, or stopped
    with its terms kept) and contains at least one character entry.
    Otherwise ``(False, reason)``.
    """
    book = await session.get(Book, book_id)
    if book is None:
        return (False, "Book not found.")
    if book.glossary_extraction_status == "running":
        return (False, "Wait for glossary extraction to finish.")
    if not glossary_ready(book):
        return (False, "Run glossary extraction first.")

    n = await session.scalar(
        select(func.count())
        .select_from(GlossaryEntry)
        .where(
            GlossaryEntry.book_id == book_id,
            GlossaryEntry.term_type == "character_name",
            GlossaryEntry.status.not_in(INACTIVE_STATUSES),
        )
    )
    if n == 0:
        return (False, "No characters in glossary.")
    return (True, None)


async def can_continue_voice_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> bool:
    """True when a prior run can resume: same window geometry and unfinished windows."""
    book = await session.get(Book, book_id)
    if book is None or book.voice_extraction_status == "running":
        return False
    manuscript = await _load_book_plaintext(session, book_id)
    wins = make_windows(manuscript) if manuscript else []
    if not wins:
        return False
    total = len(wins)
    if (
        book.voice_extraction_windows_total is not None
        and book.voice_extraction_windows_total != total
    ):
        return False
    done = book.voice_extraction_windows_completed
    if done is None:
        return False
    return done < total


# ─── Windowing ──────────────────────────────────────────


def make_windows(
    text: str,
    *,
    window_words: int = VOICE_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = VOICE_EXTRACTION_OVERLAP_WORDS,
) -> list[str]:
    """Split a manuscript into overlapping windows.

    Voice extraction uses tighter windows than glossary (500 vs 1000
    words) — closer reading, less working context for the model to
    drift on, fewer identity leaks in the prose body. The underlying
    word-splitting logic is shared with glossary; only the defaults
    differ.
    """
    return glossary_make_windows(text, window_words=window_words, overlap_words=overlap_words)


# ─── Phase 1: voice extraction ──────────────────────────


async def load_glossary_characters(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[GlossaryCharacterRef]:
    """Load all character glossary entries for the book.

    Includes ``has_voice_profile`` so the model knows whether to
    expect "create" or "extend / add candidate" operations.
    """
    _, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if not entries:
        return []
    gres = await session.execute(
        select(CharacterVoice.glossary_entry_id).where(
            CharacterVoice.book_id == book_id,
        ),
    )
    have_voice: set[UUID] = {row[0] for row in gres.all()}
    out: list[GlossaryCharacterRef] = []
    for e in entries:
        if e.term_type != "character_name" or e.status in INACTIVE_STATUSES:
            continue
        out.append(
            GlossaryCharacterRef(
                glossary_entry_id=str(e.id),
                canonical_name=e.canonical_form,
                variants=list(e.variants or []),
                has_voice_profile=e.id in have_voice,
            )
        )
    return out


async def load_glossary_characters_for_voice_window(
    session: AsyncSession,
    *,
    book_id: UUID,
    window_number: int,
    use_speaker_map: bool,
) -> list[GlossaryCharacterRef]:
    """Glossary characters eligible for voice work in one window.

    When ``use_speaker_map`` is True (Pass 1 completed), returns only
    characters with a ``WindowSpeaker`` row for ``window_number``.
    Otherwise returns the full character list (legacy / soft-gate path).
    """
    all_chars = await load_glossary_characters(session, book_id=book_id)
    if not use_speaker_map:
        return all_chars
    speakers = await speakers_service.load_speakers_for_window(
        session,
        book_id=book_id,
        window_number=window_number,
    )
    allowed = {str(s.glossary_entry_id) for s in speakers}
    return [c for c in all_chars if c.glossary_entry_id in allowed]


def _filter_profiles_to_glossary_ids(
    profiles: list[CharacterVoiceCompact],
    glossary_entry_ids: set[str],
) -> list[CharacterVoiceCompact]:
    return [p for p in profiles if p.glossary_entry_id in glossary_entry_ids]


async def load_compact_voice_profiles(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[CharacterVoiceCompact]:
    """Load profiles in the lean shape the extraction prompt expects.

    Includes source_voice_observation, target_voice_strategy, candidate count,
    and candidate reasons
    (the ``why_representative`` field of each candidate, in order
    they were added). Does NOT include candidate source texts — those
    are too long for prompt context, and the model only needs the
    reasons to judge whether new candidates would duplicate the pool.
    """
    stmt = (
        select(CharacterVoice)
        .join(GlossaryEntry, GlossaryEntry.id == CharacterVoice.glossary_entry_id)
        .where(
            CharacterVoice.book_id == book_id,
            CharacterVoice.status != "rejected",
        )
        .options(
            selectinload(CharacterVoice.glossary_entry),
            selectinload(CharacterVoice.candidates),
        )
        .order_by(GlossaryEntry.canonical_form.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    result: list[CharacterVoiceCompact] = []
    for v in rows:
        g = v.glossary_entry
        if g is None:
            continue
        cands = sorted(list(v.candidates), key=lambda c: (c.created_at, c.id))
        result.append(
            CharacterVoiceCompact(
                id=str(v.id),
                glossary_entry_id=str(v.glossary_entry_id),
                canonical_name=g.canonical_form,
                source_voice_observation=v.source_voice_observation,
                target_voice_strategy=v.target_voice_strategy,
                candidate_count=len(cands),
                candidate_reasons=[c.why_representative for c in cands],
                last_observed_window=v.last_observed_window,
            )
        )
    return result


async def load_previous_notepad(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[VoiceNote]:
    """Load the voice notepad from the end of the previous pass."""
    row = await session.get(VoiceNotepad, book_id)
    if row is None or not row.notes:
        return []
    return TypeAdapter(list[VoiceNote]).validate_python(list(row.notes))


def filter_delta_for_profile(
    delta: VoiceUpdate,
    *,
    profile_id: str,
    glossary_entry_id: str,
) -> VoiceUpdate:
    """Keep only operations targeting one voice profile."""
    pid = str(profile_id)
    gid = str(glossary_entry_id)
    return VoiceUpdate(
        window_summary=delta.window_summary,
        new_profiles=[p for p in delta.new_profiles if p.glossary_entry_id == gid],
        extensions=[e for e in delta.extensions if e.profile_id == pid],
        candidate_additions=[a for a in delta.candidate_additions if a.profile_id == pid],
        candidate_replacements=[r for r in delta.candidate_replacements if r.profile_id == pid],
        notepad=list(delta.notepad),
    )


async def apply_delta(
    session: AsyncSession,
    *,
    book_id: UUID,
    delta: VoiceUpdate,
    window_number: int,
    glossary_characters: list[GlossaryCharacterRef] | None = None,
    update_notepad: bool = True,
) -> None:
    """Apply a chain's delta to the persisted state.

    Order matters:

      1. Run the ID+name cross-checks via ``voice_validation``. Drop
         operations that fail; log warnings. The rest of this function
         operates on the filtered set.
      2. Apply ``extensions`` — UPDATE source_voice_observation and/or
         target_voice_strategy on existing profiles, refresh
         last_observed_window.
      3. Apply ``candidate_replacements`` — for each, find the
         candidate row whose ``why_representative`` matches the
         operation's ``remove_candidate_reason`` (case-sensitive,
         exact match). DELETE that row, INSERT the new candidate. If
         no match found, drop the operation and log a warning.
      4. Apply ``candidate_additions`` — for each, check the voice's
         current candidate count. If < 8, INSERT. If >= 8, drop and
         log a warning (the model should have used a replacement
         instead).
      5. Insert ``new_profiles`` — INSERT character_voice with
         status='proposed', first_seen_window=window_number. For each
         initial_candidate, INSERT a voice_passage_candidate row.
      6. Replace the notepad row entirely with delta.notepad.
      7. Update last_observed_window for every profile that received
         any operation.

    All as one transaction. Retryable on failure without state
    corruption.

    When ``glossary_characters`` is passed (speaker-scoped window), only
    operations targeting those glossary entries are accepted; profiles
    in the cross-check map are limited to the same scope.
    """
    chars = (
        glossary_characters
        if glossary_characters is not None
        else await load_glossary_characters(session, book_id=book_id)
    )
    glossary_name_by_id = {c.glossary_entry_id: c.canonical_name for c in chars}
    allowed_glossary_ids = set(glossary_name_by_id)
    profiles = _filter_profiles_to_glossary_ids(
        await load_compact_voice_profiles(session, book_id=book_id),
        allowed_glossary_ids,
    )
    profile_name_by_id = {p.id: p.canonical_name for p in profiles}

    new_p = voice_validation.filter_new_profiles(
        list(delta.new_profiles), glossary_name_by_id=glossary_name_by_id
    )
    exts = voice_validation.filter_extend_ops(
        list(delta.extensions), profile_name_by_id=profile_name_by_id
    )
    repls = voice_validation.filter_candidate_replacements(
        list(delta.candidate_replacements), profile_name_by_id=profile_name_by_id
    )
    adds = voice_validation.filter_add_candidate_ops(
        list(delta.candidate_additions), profile_name_by_id=profile_name_by_id
    )

    for ext_op in exts:
        try:
            pid = UUID(str(ext_op.profile_id))
        except ValueError:
            log.warning("Voice extend: invalid profile_id %r", ext_op.profile_id)
            continue
        voice_row = await session.get(CharacterVoice, pid)
        if voice_row is None or voice_row.book_id != book_id:
            log.warning("Voice extend: missing profile %s", ext_op.profile_id)
            continue
        if ext_op.new_source_voice_observation is not None:
            voice_row.source_voice_observation = ext_op.new_source_voice_observation
        if ext_op.new_target_voice_strategy is not None:
            voice_row.target_voice_strategy = ext_op.new_target_voice_strategy
        voice_row.last_observed_window = window_number

    for repl_op in repls:
        try:
            pid = UUID(str(repl_op.profile_id))
        except ValueError:
            log.warning("ReplaceCandidate: invalid profile_id %r", repl_op.profile_id)
            continue
        voice_row = await session.get(CharacterVoice, pid)
        if voice_row is None or voice_row.book_id != book_id:
            continue
        c_stmt = (
            select(VoicePassageCandidate)
            .where(
                VoicePassageCandidate.voice_id == voice_row.id,
                VoicePassageCandidate.why_representative == repl_op.remove_candidate_reason,
            )
            .order_by(VoicePassageCandidate.created_at.asc(), VoicePassageCandidate.id.asc())
        )
        to_remove = list((await session.execute(c_stmt)).scalars().all())
        if not to_remove:
            log.warning(
                "ReplaceCandidate: no candidate with why %r for profile %s",
                (repl_op.remove_candidate_reason[:80] if repl_op.remove_candidate_reason else ""),
                repl_op.profile_id,
            )
            continue
        if len(to_remove) > 1:
            log.warning(
                "ReplaceCandidate: %d candidates share why %r for profile %s; removing all",
                len(to_remove),
                (repl_op.remove_candidate_reason[:80] if repl_op.remove_candidate_reason else ""),
                repl_op.profile_id,
            )
        for old in to_remove:
            await session.delete(old)
        rep = VoicePassageCandidate(
            source_text=repl_op.new_candidate.source_text,
            why_representative=repl_op.new_candidate.why_representative,
            first_seen_window=window_number,
        )
        rep.voice_id = voice_row.id
        session.add(rep)
        voice_row.last_observed_window = window_number

    for add_op in adds:
        try:
            pid = UUID(str(add_op.profile_id))
        except ValueError:
            log.warning("AddCandidate: invalid profile_id %r", add_op.profile_id)
            continue
        voice_row = await session.get(CharacterVoice, pid)
        if voice_row is None or voice_row.book_id != book_id:
            continue
        n_cand = int(
            await session.scalar(
                select(func.count())
                .select_from(VoicePassageCandidate)
                .where(VoicePassageCandidate.voice_id == voice_row.id)
            )
            or 0
        )
        if n_cand >= 8:
            log.warning("AddCandidate: pool full for profile %s", add_op.profile_id)
            continue
        add_c = VoicePassageCandidate(
            source_text=add_op.candidate.source_text,
            why_representative=add_op.candidate.why_representative,
            first_seen_window=window_number,
        )
        add_c.voice_id = voice_row.id
        session.add(add_c)
        voice_row.last_observed_window = window_number

    for new_op in new_p:
        try:
            gid = UUID(str(new_op.glossary_entry_id))
        except ValueError:
            log.warning("NewVoiceProfile: invalid glossary_entry_id %r", new_op.glossary_entry_id)
            continue
        dupe = (
            await session.execute(
                select(CharacterVoice).where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.glossary_entry_id == gid,
                )
            )
        ).scalar_one_or_none()
        if dupe is not None:
            log.warning(
                "NewVoiceProfile: character already has a profile for %s", new_op.glossary_entry_id
            )
            continue
        nv = CharacterVoice(
            source_voice_observation=new_op.source_voice_observation,
            target_voice_strategy=new_op.target_voice_strategy,
            status="proposed",
            first_seen_window=window_number,
            last_observed_window=window_number,
        )
        nv.book_id = book_id
        nv.glossary_entry_id = gid
        session.add(nv)
        await session.flush()
        for c in (new_op.initial_candidates)[:8]:
            c_row = VoicePassageCandidate(
                source_text=c.source_text,
                why_representative=c.why_representative,
                first_seen_window=window_number,
            )
            c_row.voice_id = nv.id
            session.add(c_row)

    if update_notepad:
        notes_as_dicts = [n.model_dump(mode="json") for n in delta.notepad]
        n_row = await session.get(VoiceNotepad, book_id)
        if n_row is None:
            session.add(
                VoiceNotepad(
                    book_id=book_id,
                    notes=notes_as_dicts,
                    last_window_number=window_number,
                )
            )
        else:
            n_row.notes = notes_as_dicts
            n_row.last_window_number = window_number
    await session.flush()


async def _prepare_voice_for_regeneration(
    session: AsyncSession,
    *,
    voice: CharacterVoice,
) -> None:
    """Clear passage pools and voice fields before a targeted re-extraction."""
    await session.execute(
        delete(VoicePassageCandidate).where(VoicePassageCandidate.voice_id == voice.id)
    )
    await session.execute(
        delete(VoiceSelectedPassage).where(VoiceSelectedPassage.voice_id == voice.id)
    )
    voice.source_voice_observation = ""
    voice.target_voice_strategy = ""
    voice.status = "proposed"
    await session.flush()


async def can_regenerate_flagged_voices(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> tuple[bool, str | None]:
    """True when flagged profiles can be re-extracted in their speaker windows."""
    book = await session.get(Book, book_id)
    if book is None:
        return (False, "Book not found.")
    if book.voice_extraction_status == "running":
        return (False, "Voice extraction is already running.")
    if book.speakers_extraction_status != "completed":
        return (False, "Complete speaker identification first.")
    if book.voice_extraction_status != "completed":
        return (False, "Complete voice extraction first.")
    n = await session.scalar(
        select(func.count())
        .select_from(CharacterVoice)
        .where(
            CharacterVoice.book_id == book_id,
            CharacterVoice.needs_regeneration.is_(True),
        )
    )
    if not n:
        return (False, "No profiles flagged for regeneration.")
    return (True, None)


async def _glossary_ref_for_voice(
    session: AsyncSession,
    *,
    book_id: UUID,
    glossary_entry_id: UUID,
) -> GlossaryCharacterRef | None:
    chars = await load_glossary_characters(session, book_id=book_id)
    for c in chars:
        if c.glossary_entry_id == str(glossary_entry_id):
            return c
    return None


async def run_selection_for_voices(
    *,
    book_id: UUID,
    voice_ids: list[UUID],
    settings: Settings,
) -> None:
    """Phase 2 for a subset of voices (after targeted regeneration)."""
    if not voice_ids:
        return
    session_maker = get_sessionmaker()
    with propagate_attributes(session_id=str(book_id), trace_name="voice_selection"):
        async with session_maker() as session:
            v_stmt = (
                select(CharacterVoice)
                .join(
                    GlossaryEntry,
                    GlossaryEntry.id == CharacterVoice.glossary_entry_id,
                )
                .where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.id.in_(voice_ids),
                    CharacterVoice.status != "rejected",
                )
                .options(
                    selectinload(CharacterVoice.glossary_entry),
                    selectinload(CharacterVoice.candidates),
                )
            )
            voices = (await session.execute(v_stmt)).scalars().all()
            occurrence_counts: dict[UUID, int] = {}
            for v in voices:
                ge = v.glossary_entry
                if ge is not None:
                    occurrence_counts[ge.id] = ge.occurrence_count
            if not occurrence_counts:
                return
            counts = compute_passage_counts(occurrence_counts=occurrence_counts)
            book = await session.get(Book, book_id)
            if book is None:
                return
            for voice in voices:
                if not voice.candidates:
                    continue
                ge = voice.glossary_entry
                if ge is None:
                    continue
                cands = await load_candidates_for_voice(session, voice_id=voice.id)
                if not cands:
                    continue
                n_want = counts.get(ge.id, 1)
                n_want = max(1, min(n_want, len(cands), 4))
                sel = await select_passages_for_character(
                    profile_id=str(voice.id),
                    canonical_name=ge.canonical_form,
                    source_voice_observation=voice.source_voice_observation,
                    target_voice_strategy=voice.target_voice_strategy,
                    candidates=cands,
                    passage_count=n_want,
                    source_language=book.source_language,
                    target_language=book.target_language,
                    settings=settings,
                )
                if (
                    sel.profile_id != str(voice.id)
                    or sel.canonical_name.strip() != ge.canonical_form.strip()
                ):
                    log.warning(
                        "Selection mismatch for profile %s; expected name %r, got %r; skipping",
                        str(voice.id)[:8],
                        ge.canonical_form,
                        sel.canonical_name,
                    )
                    continue
                await persist_selection(session, voice_id=voice.id, selection=sel)
            await session.commit()


async def run_translation_for_voices(
    *,
    book_id: UUID,
    voice_ids: list[UUID],
    settings: Settings,
) -> None:
    """Phase 3 for selected passages belonging to the given voices."""
    if not voice_ids:
        return
    session_maker = get_sessionmaker()
    with propagate_attributes(session_id=str(book_id), trace_name="voice_translation"):
        async with session_maker() as session:
            book = await session.get(Book, book_id)
            if book is None:
                return
            terms = await load_accepted_glossary_terms(session, book_id=book_id)
            stmt = (
                select(VoiceSelectedPassage)
                .join(CharacterVoice, CharacterVoice.id == VoiceSelectedPassage.voice_id)
                .where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.id.in_(voice_ids),
                    VoiceSelectedPassage.translation_proposed.is_(None),
                )
                .options(
                    selectinload(VoiceSelectedPassage.voice).selectinload(
                        CharacterVoice.glossary_entry
                    ),
                )
            )
            to_translate = (await session.execute(stmt)).scalars().all()
            for sp in to_translate:
                voice = sp.voice
                if voice is None:
                    log.warning("voice_selected_passage missing voice: %s", sp.id)
                    continue
                ge = voice.glossary_entry
                name = ge.canonical_form if ge is not None else "—"
                out = await translate_passage(
                    selected_passage_id=str(sp.id),
                    profile_id=str(voice.id),
                    canonical_name=name,
                    source_voice_observation=voice.source_voice_observation,
                    target_voice_strategy=voice.target_voice_strategy,
                    passage_source_text=sp.source_text,
                    glossary_terms=terms,
                    source_language=book.source_language,
                    target_language=book.target_language,
                    settings=settings,
                )
                if out.selected_passage_id != str(sp.id):
                    log.warning("Translation id drift for passage %s", sp.id)
                await persist_translation(
                    session,
                    selected_passage_id=sp.id,
                    translation=out,
                )
            await session.commit()


# ─── Phase 2: passage selection ─────────────────────────


def compute_passage_counts(
    *,
    occurrence_counts: dict[UUID, int],
) -> dict[UUID, int]:
    """Determine how many reference passages each voice profile gets.

    Percentile-based across this book's characters with voice profiles:

    - Top 10% by occurrence_count → 4 passages
    - Next 15% (top 25%)          → 3 passages
    - Next 25% (top 50%)          → 2 passages
    - Bottom 50%                  → 1 passage

    Rationale: more frequently mentioned characters have more voice
    range to capture; less frequent ones don't need multiple
    calibration samples. Percentile-based makes the policy adaptive to
    the book's size and character roster — no hardcoded thresholds.

    Edge cases:
    - Single character (n=1): gets 1 passage (bottom 50% of itself).
    - Two characters: top one gets 2, bottom one gets 1.
    - Ties at percentile boundaries: the higher count wins (a tie at
      the 90th percentile boundary becomes 4 passages, not 3).

    Input: ``occurrence_counts`` maps glossary_entry_id (or voice_id —
    caller's choice, the math is the same) to the integer count.
    Output: same keys, mapped to the assigned passage count.
    """
    n = len(occurrence_counts)
    if n == 0:
        return {}
    if n == 1:
        return {next(iter(occurrence_counts.keys())): 1}

    # Sort descending by count. Ties broken by key for determinism.
    sorted_ids = sorted(
        occurrence_counts.items(),
        key=lambda kv: (-kv[1], str(kv[0])),
    )

    # Compute percentile boundaries: indices at which each bucket ends.
    # Using ceil to be generous on the high side — a 22-character book
    # rounds 10% up to 3, not down to 2.
    top_10 = math.ceil(n * 0.10)
    top_25 = math.ceil(n * 0.25)
    top_50 = math.ceil(n * 0.50)

    counts: dict[UUID, int] = {}
    for i, (key, _) in enumerate(sorted_ids):
        if i < top_10:
            counts[key] = 4
        elif i < top_25:
            counts[key] = 3
        elif i < top_50:
            counts[key] = 2
        else:
            counts[key] = 1
    return counts


def _strategy_from_recommendation(rec: dict[str, Any]) -> TranslationStrategy:
    """Map stored glossary `suggestion` to the translation contract literals."""
    raw = rec.get("suggestion")
    r = (raw if isinstance(raw, str) else "translate").lower()
    if r == "keep_original":
        return "keep_original"
    if r in ("translate", "translate_literally"):
        return "translate_literally"
    if r == "transliterate":
        return "transliterate"
    if r == "adapt":
        return "adapt"
    return "adapt"


def _glossary_entry_to_term_ref(e: GlossaryEntry) -> GlossaryTermRef:
    rec = e.translation_recommendation or {}
    proposed = rec.get("proposed_target")
    if isinstance(proposed, str) and proposed.strip():
        target = proposed.strip()
    else:
        target = e.canonical_form
    n_raw = rec.get("author_notes")
    if n_raw is not None and not isinstance(n_raw, str):
        n_raw = str(n_raw)
    return GlossaryTermRef(
        term_source=e.canonical_form,
        term_target=target,
        translation_strategy=_strategy_from_recommendation(rec),
        notes=(n_raw if n_raw else None),
    )


async def load_candidates_for_voice(
    session: AsyncSession,
    *,
    voice_id: UUID,
) -> list[CandidateInPool]:
    """Load all candidate passages for one voice, in insertion order."""
    stmt = (
        select(VoicePassageCandidate)
        .where(VoicePassageCandidate.voice_id == voice_id)
        .order_by(VoicePassageCandidate.created_at.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        CandidateInPool(
            source_text=c.source_text,
            why_representative=c.why_representative,
            first_seen_window=c.first_seen_window,
        )
        for c in rows
    ]


async def persist_selection(
    session: AsyncSession,
    *,
    voice_id: UUID,
    selection: PassageSelection,
) -> list[UUID]:
    """Resolve selection output to ``voice_selected_passages`` rows."""
    await session.execute(
        delete(VoiceSelectedPassage).where(VoiceSelectedPassage.voice_id == voice_id)
    )
    rank = 0
    inserted: list[UUID] = []
    for sp in selection.selected_passages:
        c_stmt = select(VoicePassageCandidate).where(
            VoicePassageCandidate.voice_id == voice_id,
            VoicePassageCandidate.source_text == sp.candidate_source_text,
        )
        cand = (await session.execute(c_stmt)).scalar_one_or_none()
        if cand is None:
            log.warning(
                "Selected passage not in pool (voice %s); skipped text %r",
                str(voice_id)[:8],
                (sp.candidate_source_text[:80] + "…")
                if len(sp.candidate_source_text) > 80
                else sp.candidate_source_text,
            )
            continue
        sp_row = VoiceSelectedPassage(
            source_text=cand.source_text,
            why_selected=sp.why_this_one,
            selection_rank=rank,
            source_candidate_id=cand.id,
            status="proposed",
        )
        sp_row.voice_id = voice_id
        session.add(sp_row)
        await session.flush()
        inserted.append(sp_row.id)
        rank += 1
    return inserted


async def run_selection_for_book(
    *,
    book_id: UUID,
    settings: Settings,
) -> None:
    """Phase 2: pick final passages from each character's pool."""
    session_maker = get_sessionmaker()
    with propagate_attributes(session_id=str(book_id), trace_name="voice_selection"):
        async with session_maker() as session:
            v_stmt = (
                select(CharacterVoice)
                .join(
                    GlossaryEntry,
                    GlossaryEntry.id == CharacterVoice.glossary_entry_id,
                )
                .where(
                    CharacterVoice.book_id == book_id,
                    CharacterVoice.status != "rejected",
                )
                .options(
                    selectinload(CharacterVoice.glossary_entry),
                    selectinload(CharacterVoice.candidates),
                )
            )
            voices = (await session.execute(v_stmt)).scalars().all()
            occurrence_counts: dict[UUID, int] = {}
            for v in voices:
                ge = v.glossary_entry
                if ge is not None:
                    occurrence_counts[ge.id] = ge.occurrence_count
            if not occurrence_counts:
                return
            counts = compute_passage_counts(occurrence_counts=occurrence_counts)
            book = await session.get(Book, book_id)
            if book is None:
                return
            for voice in voices:
                if not voice.candidates:
                    continue
                ge = voice.glossary_entry
                if ge is None:
                    continue
                cands = await load_candidates_for_voice(session, voice_id=voice.id)
                if not cands:
                    continue
                n_want = counts.get(ge.id, 1)
                n_want = max(1, min(n_want, len(cands), 4))
                sel = await select_passages_for_character(
                    profile_id=str(voice.id),
                    canonical_name=ge.canonical_form,
                    source_voice_observation=voice.source_voice_observation,
                    target_voice_strategy=voice.target_voice_strategy,
                    candidates=cands,
                    passage_count=n_want,
                    source_language=book.source_language,
                    target_language=book.target_language,
                    settings=settings,
                )
                if (
                    sel.profile_id != str(voice.id)
                    or sel.canonical_name.strip() != ge.canonical_form.strip()
                ):
                    log.warning(
                        "Selection mismatch for profile %s; expected name %r, got %r; skipping",
                        str(voice.id)[:8],
                        ge.canonical_form,
                        sel.canonical_name,
                    )
                    continue
                await persist_selection(session, voice_id=voice.id, selection=sel)
            await session.commit()


async def load_accepted_glossary_terms(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[GlossaryTermRef]:
    """Load all accepted (and adjusted) glossary terms for the book.

    Excludes proposed (unreviewed) and rejected entries. Includes the
    translation_strategy and any author notes.
    """
    stmt = select(GlossaryEntry).where(
        GlossaryEntry.book_id == book_id,
        GlossaryEntry.status.in_(("accepted", "adjusted")),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_glossary_entry_to_term_ref(e) for e in rows]


async def persist_translation(
    session: AsyncSession,
    *,
    selected_passage_id: UUID,
    translation: PassageTranslation,
) -> None:
    """Write a translation result to its voice_selected_passage row.

    UPDATE voice_selected_passages SET translation_proposed=:translation
    WHERE id=:selected_passage_id. Does NOT set translation_authoritative
    — that happens on author review.
    """
    row = await session.get(VoiceSelectedPassage, selected_passage_id)
    if row is None:
        return
    row.translation_proposed = translation.translation
    await session.flush()


async def run_translation_for_book(
    *,
    book_id: UUID,
    settings: Settings,
) -> None:
    """Phase 3: fill translation_proposed on each selected passage."""
    session_maker = get_sessionmaker()
    with propagate_attributes(session_id=str(book_id), trace_name="voice_translation"):
        async with session_maker() as session:
            book = await session.get(Book, book_id)
            if book is None:
                return
            terms = await load_accepted_glossary_terms(session, book_id=book_id)
            stmt = (
                select(VoiceSelectedPassage)
                .join(CharacterVoice, CharacterVoice.id == VoiceSelectedPassage.voice_id)
                .where(
                    CharacterVoice.book_id == book_id,
                    VoiceSelectedPassage.translation_proposed.is_(None),
                )
                .options(
                    selectinload(VoiceSelectedPassage.voice).selectinload(
                        CharacterVoice.glossary_entry
                    ),
                )
            )
            to_translate = (await session.execute(stmt)).scalars().all()
            for sp in to_translate:
                voice = sp.voice
                if voice is None:
                    log.warning("voice_selected_passage missing voice: %s", sp.id)
                    continue
                ge = voice.glossary_entry
                name = ge.canonical_form if ge is not None else "—"
                out = await translate_passage(
                    selected_passage_id=str(sp.id),
                    profile_id=str(voice.id),
                    canonical_name=name,
                    source_voice_observation=voice.source_voice_observation,
                    target_voice_strategy=voice.target_voice_strategy,
                    passage_source_text=sp.source_text,
                    glossary_terms=terms,
                    source_language=book.source_language,
                    target_language=book.target_language,
                    settings=settings,
                )
                if out.selected_passage_id != str(sp.id):
                    log.warning("Translation id drift for passage %s", sp.id)
                await persist_translation(
                    session,
                    selected_passage_id=sp.id,
                    translation=out,
                )
            await session.commit()


# ─── The author's review action ─────────────────────────


ReviewAction = Literal["accept", "adjust", "reject"]


async def set_authoritative_translation(
    session: AsyncSession,
    *,
    selected_passage_id: UUID,
    action: ReviewAction,
    edited_translation: str | None = None,
) -> None:
    """Apply the author's review action to one selected passage.

    Three cases:

    - ``accept``: status -> 'accepted'.
      translation_authoritative = translation_proposed.
      ``edited_translation`` must be None.

    - ``adjust``: status -> 'adjusted'.
      translation_authoritative = edited_translation.
      ``edited_translation`` must be a non-empty string.

    - ``reject``: status -> 'rejected'.
      translation_authoritative stays NULL.
      ``edited_translation`` must be None.

    The proposed translation is NEVER overwritten. Preserves the
    model's original output for restoration and quality tracking.

    NOTE: this is per-passage, not per-profile. The author can accept
    one of Borys's three reference passages while rejecting another.
    """
    raise NotImplementedError(
        "Single UPDATE on voice_selected_passages. Validate "
        "edited_translation arg presence/absence per action."
    )


async def set_voice_summary_authoritative(
    session: AsyncSession,
    *,
    voice_id: UUID,
    action: ReviewAction,
    edited_summary: str | None = None,
) -> None:
    """Apply the author's review action to the voice profile itself.

    Three cases (same shape as selected-passage review):

    - ``accept``: status -> 'accepted'. Observation/strategy text unchanged.
    - ``adjust``: status -> 'adjusted'. Edited summary fields as provided.
    - ``reject``: status -> 'rejected'. Observation/strategy unchanged.

    Profile and passages are reviewed independently — accepting the
    profile doesn't auto-accept its passages, and vice versa.
    """
    raise NotImplementedError(
        "Single UPDATE on character_voices. Validate edited_summary "
        "arg presence/absence per action."
    )


# ─── Targeted regeneration ──────────────────────────────


async def regenerate_flagged_voices(
    *,
    book_id: UUID,
    settings: Settings,
) -> None:
    """Re-extract only profiles flagged ``needs_regeneration``, window by window.

    For each flagged character, visits only windows where Pass 1 mapped
    them as a speaker, updates that profile alone, then re-runs selection
    and translation for those profiles.
    """
    if not settings.GEMINI_API_KEY:
        session_local = get_sessionmaker()
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.voice_extraction_status = "failed"
                b.voice_extraction_last_error = "GEMINI_API_KEY not configured."
            await session.commit()
        log.warning("voice_regeneration_skipped_no_key", book_id=str(book_id))
        return

    session_local = get_sessionmaker()
    try:
        async with session_local() as session:
            plaintext = await _load_book_plaintext(session, book_id)
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("voice_regeneration_book_missing", book_id=str(book_id))
                return
            win_list = make_windows(plaintext)
            total_manuscript_windows = len(win_list)
            flagged = list(
                (
                    await session.execute(
                        select(CharacterVoice)
                        .where(
                            CharacterVoice.book_id == book_id,
                            CharacterVoice.needs_regeneration.is_(True),
                        )
                        .order_by(CharacterVoice.created_at.asc())
                    )
                ).scalars().all()
            )
            if not flagged:
                return

            work: list[tuple[CharacterVoice, list[int]]] = []
            for voice in flagged:
                speaker_rows = await speakers_service.load_speakers_for_character(
                    session,
                    book_id=book_id,
                    glossary_entry_id=voice.glossary_entry_id,
                )
                windows = sorted({ws.window_number for ws in speaker_rows})
                if not windows:
                    log.warning(
                        "voice_regeneration_no_speaker_windows",
                        book_id=str(book_id),
                        voice_id=str(voice.id),
                    )
                    voice.needs_regeneration = False
                    continue
                work.append((voice, windows))

            await session.commit()

            if not work:
                async with session_local() as s_done:
                    b_done = await s_done.get(Book, book_id)
                    if b_done is not None:
                        b_done.voice_extraction_status = "completed"
                        b_done.voice_extraction_last_error = None
                        _clear_voice_progress_fields(b_done)
                    await s_done.commit()
                return

            total_steps = sum(len(windows) for _, windows in work)
            regenerated_ids: list[UUID] = []

        async with session_local() as s_init:
            b0 = await s_init.get(Book, book_id)
            if b0 is not None:
                b0.voice_extraction_cancel_requested = False
                b0.voice_extraction_windows_total = total_steps
                b0.voice_extraction_windows_completed = 0
            await s_init.commit()

        cancelled = False
        completed_steps = 0
        regen_notepad: list[VoiceNote] = []

        with propagate_attributes(
            session_id=str(book_id),
            trace_name="voice_regeneration",
        ):
            for voice, windows in work:
                async with session_local() as session:
                    book = await session.get(Book, book_id)
                    if book is None:
                        raise RuntimeError("book disappeared during voice regeneration")
                    if book.voice_extraction_cancel_requested:
                        await _finalize_voice_cancelled(session, book_id=book_id)
                        cancelled = True
                        break

                    voice_row = await session.get(CharacterVoice, voice.id)
                    if voice_row is None:
                        continue
                    await _prepare_voice_for_regeneration(session, voice=voice_row)
                    await session.commit()

                profile_id = str(voice.id)
                glossary_entry_id = voice.glossary_entry_id
                regenerated_ids.append(voice.id)

                for step_idx, window_number in enumerate(windows):
                    async with session_local() as session:
                        book = await session.get(Book, book_id)
                        if book is None:
                            raise RuntimeError("book disappeared during voice regeneration")
                        if book.voice_extraction_cancel_requested:
                            await _finalize_voice_cancelled(session, book_id=book_id)
                            cancelled = True
                            break

                        if window_number < 1 or window_number > total_manuscript_windows:
                            log.warning(
                                "voice_regeneration_window_out_of_range",
                                book_id=str(book_id),
                                window=window_number,
                                total=total_manuscript_windows,
                            )
                            completed_steps += 1
                            book.voice_extraction_windows_completed = completed_steps
                            await session.commit()
                            continue

                        char_ref = await _glossary_ref_for_voice(
                            session,
                            book_id=book_id,
                            glossary_entry_id=glossary_entry_id,
                        )
                        if char_ref is None:
                            log.warning(
                                "voice_regeneration_missing_glossary_character",
                                book_id=str(book_id),
                                glossary_entry_id=str(glossary_entry_id),
                            )
                            completed_steps += 1
                            book.voice_extraction_windows_completed = completed_steps
                            await session.commit()
                            continue

                        characters = [char_ref]
                        allowed_ids = {char_ref.glossary_entry_id}
                        current = _filter_profiles_to_glossary_ids(
                            await load_compact_voice_profiles(session, book_id=book_id),
                            allowed_ids,
                        )
                        wtext = win_list[window_number - 1]
                        delta = await extract_voices_window(
                            window_text=wtext,
                            glossary_characters=characters,
                            current_profiles=current,
                            previous_notepad=regen_notepad,
                            window_number=window_number,
                            total_windows=total_manuscript_windows,
                            source_language=book.source_language,
                            target_language=book.target_language,
                            settings=settings,
                            speakers_scoped=True,
                            regeneration_pass=step_idx == 0,
                        )
                        scoped = filter_delta_for_profile(
                            delta,
                            profile_id=profile_id,
                            glossary_entry_id=str(glossary_entry_id),
                        )
                        regen_notepad = list(scoped.notepad)
                        await apply_delta(
                            session,
                            book_id=book_id,
                            delta=scoped,
                            window_number=window_number,
                            glossary_characters=characters,
                            update_notepad=False,
                        )
                        completed_steps += 1
                        book.voice_extraction_windows_completed = completed_steps
                        await session.commit()

                    if cancelled:
                        break

                if not cancelled:
                    async with session_local() as session:
                        voice_row = await session.get(CharacterVoice, voice.id)
                        if voice_row is not None:
                            voice_row.needs_regeneration = False
                        await session.commit()

                if cancelled:
                    break

        if cancelled:
            return

        try:
            await run_selection_for_voices(
                book_id=book_id,
                voice_ids=regenerated_ids,
                settings=settings,
            )
            await run_translation_for_voices(
                book_id=book_id,
                voice_ids=regenerated_ids,
                settings=settings,
            )
        except Exception as exc2:
            log.exception(
                "voice_regeneration_post_phases_failed",
                book_id=str(book_id),
                err=str(exc2)[:2000],
            )
            async with session_local() as s5:
                b2 = await s5.get(Book, book_id)
                if b2 is not None:
                    b2.voice_extraction_status = "failed"
                    b2.voice_extraction_last_error = (str(exc2) or type(exc2).__name__)[:5000]
                await s5.commit()
            return

        async with session_local() as s6:
            b3 = await s6.get(Book, book_id)
            if b3 is not None:
                b3.voice_extraction_status = "completed"
                b3.voice_extraction_last_error = None
                b3.voice_extraction_cancel_requested = False
                _clear_voice_progress_fields(b3)
            await s6.commit()
        log.info(
            "voice_regeneration_completed",
            book_id=str(book_id),
            profile_count=len(regenerated_ids),
        )

    except GenerationDisabledError:
        async with session_local() as session:
            bb = await session.get(Book, book_id)
            if bb is not None:
                bb.voice_extraction_status = "failed"
                bb.voice_extraction_last_error = "LLM generation disabled (missing API key)."
                bb.voice_extraction_cancel_requested = False
            await session.commit()
    except Exception as exc:
        log.exception("voice_regeneration_failed", book_id=str(book_id))
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.voice_extraction_status = "failed"
                b.voice_extraction_last_error = (str(exc) or type(exc).__name__)[:5000]
                b.voice_extraction_cancel_requested = False
            await session.commit()


# ─── Top-level orchestration ────────────────────────────


async def extract_book_voices(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
    cost_limit: bool = True,
) -> None:
    """Background task: run voice windows, then selection and translation for a book.

    During the windows the run pauses like Stop when its real cost goes more
    than ``COST_PAUSE_THRESHOLD`` over the estimate for the windows done so
    far, unless ``cost_limit`` is off. Selection and translation afterwards
    are counted in the spend but not paused (see ``app.services.cost_guard``).
    """
    if not settings.GEMINI_API_KEY:
        session_local = get_sessionmaker()
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.voice_extraction_status = "failed"
                b.voice_extraction_last_error = "GEMINI_API_KEY not configured."
                if not continue_extraction:
                    _clear_voice_progress_fields(b)
                await session.commit()
        log.warning("voice_skipped_no_key", book_id=str(book_id))
        return

    session_local = get_sessionmaker()
    try:
        async with session_local() as session:
            plaintext = await _load_book_plaintext(session, book_id)
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("voice_book_missing", book_id=str(book_id))
                return
            win_list = make_windows(plaintext)
            total = len(win_list)
            if not continue_extraction:
                start_window = 1
            else:
                if (
                    book.voice_extraction_windows_total is not None
                    and book.voice_extraction_windows_total != total
                ):
                    book.voice_extraction_status = "failed"
                    book.voice_extraction_last_error = (
                        "Manuscript windowing changed; cannot continue. Start a new run."
                    )
                    await session.commit()
                    return
                done = book.voice_extraction_windows_completed or 0
                start_window = done + 1

        if total == 0:
            async with session_local() as s2:
                b = await s2.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_status = "completed"
                    b.voice_extraction_last_error = None
                    b.voice_extraction_cancel_requested = False
                    _clear_voice_progress_fields(b)
                await s2.commit()
            log.info("voice_extraction_empty_manuscript", book_id=str(book_id))
            return

        if start_window > total:
            async with session_local() as s3:
                b = await s3.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_status = "completed"
                    b.voice_extraction_last_error = None
                    b.voice_extraction_cancel_requested = False
                    _clear_voice_progress_fields(b)
                await s3.commit()
            return

        async with session_local() as s4:
            b0 = await s4.get(Book, book_id)
            if b0 is None:
                raise RuntimeError("book disappeared during voice extraction")
            b0.voice_extraction_cancel_requested = False
            b0.voice_extraction_windows_total = total
            b0.voice_extraction_windows_completed = start_window - 1
            # The window phase alone: the estimate with no characters to select for.
            windows_cost = estimate_voice_extraction(
                word_count=b0.word_count, character_count=0, settings=settings
            ).pass2.estimated_cost_usd
            guard = start_guard(
                b0,
                "voices",
                settings=settings,
                expected=linear(windows_cost, total),
                units_total=total,
                start_units=start_window - 1,
                limit=cost_limit,
            )
            await s4.commit()

        cancelled = False
        with (
            propagate_attributes(session_id=str(book_id), trace_name="voice_extraction"),
            counting(guard.spend),
        ):
            for n in range(start_window, total + 1):
                wtext = win_list[n - 1]
                async with session_local() as session:
                    book = await session.get(Book, book_id)
                    if book is None:
                        raise RuntimeError("book disappeared during voice extraction")
                    if book.voice_extraction_cancel_requested:
                        await _finalize_voice_cancelled(
                            session,
                            book_id=book_id,
                        )
                        cancelled = True
                        break
                    use_speaker_map = book.speakers_extraction_status == "completed"
                    characters = await load_glossary_characters_for_voice_window(
                        session,
                        book_id=book_id,
                        window_number=n,
                        use_speaker_map=use_speaker_map,
                    )
                    if use_speaker_map and not characters:
                        book.voice_extraction_windows_completed = n
                        await session.commit()
                        if n % 5 == 0 or n == total:
                            log.info(
                                "voice_extraction_window_skipped_no_speakers",
                                book_id=str(book_id),
                                window=n,
                                total_windows=total,
                            )
                        continue
                    if not characters:
                        msg = "No character glossary entries available for this book."
                        book.voice_extraction_status = "failed"
                        book.voice_extraction_last_error = msg
                        book.voice_extraction_cancel_requested = False
                        await session.commit()
                        return
                    allowed_ids = {c.glossary_entry_id for c in characters}
                    current = _filter_profiles_to_glossary_ids(
                        await load_compact_voice_profiles(session, book_id=book_id),
                        allowed_ids,
                    )
                    previous = await load_previous_notepad(session, book_id=book_id)
                    delta = await extract_voices_window(
                        window_text=wtext,
                        glossary_characters=characters,
                        current_profiles=current,
                        previous_notepad=previous,
                        window_number=n,
                        total_windows=total,
                        source_language=book.source_language,
                        target_language=book.target_language,
                        settings=settings,
                        speakers_scoped=use_speaker_map,
                    )
                    await apply_delta(
                        session,
                        book_id=book_id,
                        delta=delta,
                        window_number=n,
                        glossary_characters=characters,
                    )
                    book.voice_extraction_windows_completed = n
                    guard.units_done = n
                    reason = guard.overrun() if n < total else None
                    save_state(book, guard)
                    if reason:
                        book.voice_extraction_cancel_requested = True
                        log.warning(
                            "voice_extraction_cost_pause", book_id=str(book_id), reason=reason
                        )
                    await session.commit()
                if n % 5 == 0 or n == total:
                    log.info(
                        "voice_extraction_progress",
                        book_id=str(book_id),
                        window=n,
                        total_windows=total,
                    )

        if cancelled:
            return

        try:
            with counting(guard.spend):
                await run_selection_for_book(book_id=book_id, settings=settings)
                await run_translation_for_book(book_id=book_id, settings=settings)
        except Exception as exc2:
            log.exception(
                "voice_post_extraction_phases_failed",
                book_id=str(book_id),
                err=str(exc2)[:2000],
            )
            async with session_local() as s5:
                b2 = await s5.get(Book, book_id)
                if b2 is not None:
                    b2.voice_extraction_status = "failed"
                    b2.voice_extraction_last_error = (str(exc2) or type(exc2).__name__)[:5000]
                await s5.commit()
            return

        async with session_local() as s6:
            b3 = await s6.get(Book, book_id)
            if b3 is not None:
                save_state(b3, guard)
                b3.voice_extraction_status = "completed"
                b3.voice_extraction_last_error = None
                b3.voice_extraction_cancel_requested = False
                _clear_voice_progress_fields(b3)
            await s6.commit()
        log.info("voice_pipeline_completed", book_id=str(book_id))

    except GenerationDisabledError:
        async with session_local() as session:
            bb = await session.get(Book, book_id)
            if bb is not None:
                bb.voice_extraction_status = "failed"
                bb.voice_extraction_last_error = "LLM generation disabled (missing API key)."
                bb.voice_extraction_cancel_requested = False
            await session.commit()
    except Exception as exc:
        log.exception("voice_extraction_failed", book_id=str(book_id))
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.voice_extraction_status = "failed"
                b.voice_extraction_last_error = (str(exc) or type(exc).__name__)[:5000]
                b.voice_extraction_cancel_requested = False
            await session.commit()


async def run_voice_pipeline_for_book(
    *,
    book_id: UUID,
    settings: Settings,
) -> None:
    """End-to-end driver: phases 1 → 2 → 3 in sequence.

    Layout::

        ok, reason = await can_run_voice_extraction(...)
        if not ok:
            mark_status_failed(reason); return

        # Phase 1: extraction
        await run_extraction_for_book(book_id=book_id, settings=settings)

        # Phase 2: selection
        await run_selection_for_book(book_id=book_id, settings=settings)

        # Phase 3: translation
        await run_translation_for_book(book_id=book_id, settings=settings)

    Each phase sets its own status flag on the books row as it
    starts/completes. Failure in any phase stops the pipeline and
    leaves partial work persisted (the user can resume from where it
    stopped via the same orchestration, since each phase reads its
    inputs from the database).

    For Langfuse tracing, set ``session_id=str(book_id)`` on every
    chain call so all three phases for a book group together.
    """
    raise NotImplementedError(
        "Tie the three phases together. Each phase has its own driver "
        "function above; this function just sequences them and handles "
        "top-level error reporting."
    )


async def run_extraction_for_book(
    *,
    book_id: UUID,
    settings: Settings,
) -> None:
    """Run the full voice pipeline (same as ``extract_book_voices`` with no resume)."""
    await extract_book_voices(book_id=book_id, settings=settings, continue_extraction=False)
