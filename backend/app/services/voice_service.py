"""Voice extraction service — boundary between LLM output and persisted state.

This module owns:

1. **Precondition check.** Voice extraction requires a completed
   glossary with at least one ``character_name`` entry.
2. **Loading character context.** Every glossary character (status !=
   rejected) becomes a ``GlossaryCharacterRef`` in the prompt.
3. **Compacting profiles.** Persisted ``CharacterVoice`` rows become
   ``CharacterVoiceCompact`` for the prompt input — full voice_summary
   plus the reference_passage_source (no translation, by design).
4. **Applying the delta.** Translating ``new_profiles`` /
   ``extensions`` / ``reference_replacements`` into DB writes.
5. **Counting dialogue volume.** Code-side scan of the window for
   quoted speech attributable to each character. Don't trust the model
   on counts.
6. **Orchestrating** the iteration.
7. **Setting authoritative translation.** When the author reviews a
   profile, this module updates
   ``reference_passage_translation_authoritative`` and ``status``
   accordingly.

Service functions implement the contract between the voice chain and
persistence (glossary snapshot, window loop, delta application, review).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from langfuse import propagate_attributes
from sqlalchemy import select, update

from app.constants.glossary_taxonomy import normalize_stored_term_type
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.generation import GenerationDisabledError
from app.generation.chains.extract_voices_chain import extract_voices_window
from app.generation.prompt_manager.models.extract_voices_model import (
    CharacterVoiceCompact,
    GlossaryCharacterRef,
    VoiceNote,
    VoiceUpdate,
)
from app.models.book import Book
from app.models.glossary import GlossaryEntry
from app.models.voice import CharacterVoice, VoiceNotepad
from app.schemas.voice import (
    VoiceWorkingProfileOut,
    VoiceWorkingProfilePatchIn,
    WorkingVoicesResponse,
)
from app.services.glossary_service import (
    _load_book_plaintext,
    load_working_glossary_for_latest_run,
    make_windows,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)


def _clear_book_voice_progress_fields(book: Book) -> None:
    book.voice_extraction_windows_total = None
    book.voice_extraction_windows_completed = None


_STALE_STARTUP_MSG = (
    "Extraction was not running (server restarted, or the background worker never "
    "started). Use Continue if you had partial progress, or start the run again."
)


async def reconcile_stale_voice_runs_on_startup() -> int:
    """Mark any book still ``running`` as failed. Call once per API process on boot.

    After a container crash or ``uvicorn`` reload, in-process work is gone but the
    database can still say ``running`` — the UI and Langfuse look stuck forever.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        res = await session.execute(
            update(Book)
            .where(Book.voice_extraction_status == "running")
            .values(
                voice_extraction_status="failed",
                voice_extraction_last_error=_STALE_STARTUP_MSG,
                voice_extraction_cancel_requested=False,
            ),
        )
        await session.commit()
        n = int(res.rowcount or 0)
    if n:
        log.info("voice_reconciled_stale_running_on_startup", count=n)
    return n


async def _reconcile_stuck_running_voice(
    book_id: UUID,
    *,
    default_message: str = (
        "Voice extraction did not complete (it may have been interrupted or the "
        "server restarted during the run). Use Continue to resume, or check logs."
    ),
) -> None:
    """If the book is still ``running``, mark ``failed`` so the UI is never stuck.

    Background work can exit without an ``except`` handler: early returns that
    forgot to set status, ``BaseException``s that bypass ``Exception``, or
    in-process work ending before the per-window commit after status was set to
    ``running`` in the API.
    """
    session_factory = get_sessionmaker()
    try:
        async with session_factory() as session:
            b = await session.get(Book, book_id)
            if b is None or b.voice_extraction_status != "running":
                return
            b.voice_extraction_status = "failed"
            b.voice_extraction_last_error = (b.voice_extraction_last_error or default_message)[
                :5000
            ]
            b.voice_extraction_cancel_requested = False
            await session.commit()
    except Exception:
        log.exception("voice_reconcile_stuck_running_failed", book_id=str(book_id))


# ─── Precondition ───────────────────────────────────────


async def can_run_voice_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> tuple[bool, str | None]:
    """Check whether voice extraction can proceed for this book.

    Returns ``(True, None)`` if the glossary is completed and contains
    at least one character entry. Returns ``(False, reason)`` otherwise,
    where ``reason`` is a short string the API surfaces to the user.

    Two distinct failure modes:

    - Glossary status != 'completed' → "Run glossary extraction first."
    - Glossary completed but 0 character entries → "This manuscript's
      glossary contains no characters; voice extraction has nothing to
      attach profiles to."
    """
    book = await session.get(Book, book_id)
    if book is None:
        return (False, "Book not found.")

    if book.glossary_extraction_status != "completed":
        return (False, "Run glossary extraction first.")

    stmt = select(GlossaryEntry).where(
        GlossaryEntry.book_id == book_id,
        GlossaryEntry.status != "rejected",
    )
    entries = (await session.execute(stmt)).scalars().all()
    n_characters = sum(
        1
        for e in entries
        if normalize_stored_term_type(e.term_type) == "character_name"
    )
    if n_characters == 0:
        return (
            False,
            "This manuscript's glossary contains no characters; voice extraction has nothing to attach profiles to.",
        )
    return (True, None)


async def can_continue_voice_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> bool:
    """True when a failed/cancelled run left windows unprocessed and preconditions still hold."""
    ok, _ = await can_run_voice_extraction(session, book_id=book_id)
    if not ok:
        return False
    book = await session.get(Book, book_id)
    if book is None:
        return False
    if book.voice_extraction_status not in ("failed", "cancelled"):
        return False
    total = book.voice_extraction_windows_total
    if total is None or total < 1:
        return False
    done = book.voice_extraction_windows_completed
    n_done = 0 if done is None else int(done)
    return n_done < total


# ─── Windowing ──────────────────────────────────────────
# `make_windows` is imported from glossary_service — same word windows and
# overlap as glossary extraction so voice and glossary align on segment bounds.


# ─── State <-> compact form ─────────────────────────────


async def load_glossary_characters(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[GlossaryCharacterRef]:
    """Load all character glossary entries for the book.

    Includes ``has_voice_profile`` per character so the model knows
    whether to expect a "create" or an "extend / replace reference"
    operation. Skips rejected entries — the model has no business
    proposing voice work for characters the author dismissed.
    """
    run, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if run is None or not entries:
        return []
    vq = await session.execute(
        select(CharacterVoice.glossary_entry_id).where(
            CharacterVoice.book_id == book_id,
            CharacterVoice.status != "rejected",
        ),
    )
    with_voice = set(vq.scalars().all())
    out: list[GlossaryCharacterRef] = []
    for e in entries:
        if e.status == "rejected":
            continue
        if normalize_stored_term_type(e.term_type) != "character_name":
            continue
        out.append(
            GlossaryCharacterRef(
                glossary_entry_id=str(e.id),
                canonical_name=e.canonical_form,
                variants=list(e.variants or []),
                has_voice_profile=e.id in with_voice,
            ),
        )
    out.sort(key=lambda x: x.canonical_name.lower())
    return out


async def load_compact_voice_profiles(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[CharacterVoiceCompact]:
    """Load persisted profiles in the lean shape the prompt expects.

    Includes the full voice_summary and the reference_passage_source.
    Excludes the translation half of the reference passage — the model
    is selecting source passages, not auditing its own prior
    translations.

    Skips rejected profiles (status='rejected').
    """
    stmt = (
        select(CharacterVoice, GlossaryEntry.canonical_form)
        .join(GlossaryEntry, GlossaryEntry.id == CharacterVoice.glossary_entry_id)
        .where(
            CharacterVoice.book_id == book_id,
            CharacterVoice.status != "rejected",
        )
        .order_by(GlossaryEntry.canonical_form.asc())
    )
    result = await session.execute(stmt)
    return [
        CharacterVoiceCompact(
            id=str(v.id),
            glossary_entry_id=str(v.glossary_entry_id),
            canonical_name=canonical,
            voice_summary=v.voice_summary,
            reference_passage_source=v.reference_passage_source,
            last_observed_window=v.last_observed_window,
        )
        for v, canonical in result.all()
    ]


async def load_previous_notepad(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[VoiceNote]:
    """Load the voice notepad as it was at the end of the previous pass."""
    row = await session.get(VoiceNotepad, book_id)
    if row is None or not row.notes:
        return []
    out: list[VoiceNote] = []
    for item in row.notes:
        if not isinstance(item, dict):
            continue
        try:
            out.append(VoiceNote.model_validate(item))
        except Exception:
            continue
    return out


# ─── Delta application ──────────────────────────────────


async def apply_delta(
    session: AsyncSession,
    *,
    book_id: UUID,
    delta: VoiceUpdate,
    window_text: str,
    window_number: int,
) -> None:
    """Translate a chain's delta into DB writes.

    Order matters:

      1. Apply ``extensions`` first — UPDATE voice_summary on existing
         profiles. Keeps these from racing against new_profile inserts
         in the same transaction.
      2. Apply ``reference_replacements`` — UPDATE
         reference_passage_source AND reference_passage_translation_proposed
         on existing profiles. Crucially, this also resets
         reference_passage_translation_authoritative to NULL — if the
         author had previously accepted a translation and the model now
         provides a better passage, the new translation hasn't been
         reviewed yet, so it shouldn't count as authoritative. (Also
         flip status back to 'proposed' if the row was previously
         accepted/adjusted; the new passage needs review.)
      3. Insert ``new_profiles`` — these become rows with
         status='proposed', first_seen_window=window_number, full
         voice_summary, reference_passage_source, and
         reference_passage_translation_proposed populated.
         translation_authoritative stays NULL until review.
      4. Replace the notepad row entirely with delta.notepad.
      5. Update ``dialogue_volume_observed`` and ``last_observed_window``
         for every profile that received any operation. Volume is
         incremented by ``count_dialogue_turns()`` — service code
         scans the window text for quoted speech attributable to
         each character. Do NOT trust the model on counts.

    All operations happen in one transaction. If any fails, nothing
    persists — extraction can be retried for this window without
    corrupting state.
    """
    touched_ids: set[UUID] = set()

    for ext in delta.extensions:
        try:
            pid = UUID(ext.profile_id)
        except (ValueError, TypeError):
            log.warning("voice_ext_bad_profile_id", profile_id=ext.profile_id)
            continue
        row = await session.get(CharacterVoice, pid)
        if row is None or row.book_id != book_id:
            log.warning("voice_ext_missing_profile", profile_id=str(ext.profile_id))
            continue
        row.voice_summary = ext.new_voice_summary
        row.last_observed_window = window_number
        touched_ids.add(row.id)

    for rep in delta.reference_replacements:
        try:
            pid = UUID(rep.profile_id)
        except (ValueError, TypeError):
            continue
        row = await session.get(CharacterVoice, pid)
        if row is None or row.book_id != book_id:
            continue
        row.reference_passage_source = rep.new_reference_passage_source
        row.reference_passage_translation_proposed = rep.new_reference_passage_translation
        row.reference_passage_translation_authoritative = None
        row.status = "proposed"
        row.last_observed_window = window_number
        touched_ids.add(row.id)

    for np in delta.new_profiles:
        try:
            gid = UUID(np.glossary_entry_id)
        except (ValueError, TypeError):
            continue
        entry = await session.get(GlossaryEntry, gid)
        if entry is None or entry.book_id != book_id or entry.status == "rejected":
            continue
        if normalize_stored_term_type(entry.term_type) != "character_name":
            continue
        existing_q = await session.execute(
            select(CharacterVoice).where(
                CharacterVoice.book_id == book_id,
                CharacterVoice.glossary_entry_id == gid,
            ),
        )
        existing = existing_q.scalar_one_or_none()
        if existing is not None:
            log.info(
                "voice_new_profile_treated_as_update",
                glossary_entry_id=str(gid),
            )
            existing.voice_summary = np.voice_summary
            existing.reference_passage_source = np.reference_passage_source
            existing.reference_passage_translation_proposed = (
                np.reference_passage_translation
            )
            existing.reference_passage_translation_authoritative = None
            existing.status = "proposed"
            existing.last_observed_window = window_number
            touched_ids.add(existing.id)
            continue
        v = CharacterVoice(
            voice_summary=np.voice_summary,
            reference_passage_source=np.reference_passage_source,
            reference_passage_translation_proposed=np.reference_passage_translation,
            first_seen_window=window_number,
            last_observed_window=window_number,
        )
        v.glossary_entry_id = gid
        v.book_id = book_id
        v.id = uuid4()
        session.add(v)
        await session.flush()
        touched_ids.add(v.id)

    notes_payload = [n.model_dump(mode="json") for n in delta.notepad]
    notepad_row = await session.get(VoiceNotepad, book_id)
    if notepad_row is None:
        session.add(
            VoiceNotepad(
                book_id=book_id,
                notes=notes_payload,
                last_window_number=window_number,
            ),
        )
    else:
        notepad_row.notes = notes_payload
        notepad_row.last_window_number = window_number

    for vid in touched_ids:
        row = await session.get(CharacterVoice, vid)
        if row is None:
            continue
        entry = await session.get(GlossaryEntry, row.glossary_entry_id)
        if entry is None:
            continue
        n_turns = count_dialogue_turns(
            window_text,
            canonical_name=entry.canonical_form,
            variants=list(entry.variants or []),
        )
        row.dialogue_volume_observed = int(row.dialogue_volume_observed) + n_turns
        row.last_observed_window = window_number


def _names_for_attribution(canonical_name: str, variants: list[str]) -> list[str]:
    names: list[str] = [canonical_name] + [v for v in (variants or []) if v and str(v).strip()]
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        k = n.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(n.strip())
    return out


def _name_in_haystack(haystack: str, names: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in names if n)


def _quote_spans(window_text: str) -> list[tuple[int, int]]:
    spans: set[tuple[int, int]] = set()
    for pat in (re.compile(r'"[^"]*"'), re.compile(r"„[^”]+”")):
        for m in pat.finditer(window_text):
            spans.add((m.start(), m.end()))
    return sorted(spans, key=lambda t: t[0])


def count_dialogue_turns(
    window_text: str,
    *,
    canonical_name: str,
    variants: list[str],
) -> int:
    """Count dialogue turns in this window attributable to a character.

    Used by ``apply_delta`` to update dialogue_volume_observed honestly,
    independent of whatever the model claimed about dialogue density.

    The implementation should:

    1. Find quoted speech segments in ``window_text``. For Polish, this
       includes both standard quote characters AND em-dash dialogue
       openers (``— Aurel zawahał się``). Other source languages will
       have different conventions.
    2. For each segment, check whether the surrounding 50 characters
       (before and after) include the canonical name or any variant.
    3. Return the count of matched segments.

    Imperfect — the model is still better at attribution than regex.
    But this provides an honest *floor* on the count. Translation can
    weight profiles by dialogue_volume_observed when picking which
    voices need the most calibration help.
    """
    names = _names_for_attribution(canonical_name, variants)
    if not names:
        return 0
    n = 0
    for start, end in _quote_spans(window_text):
        lo = max(0, start - 50)
        hi = min(len(window_text), end + 50)
        ctx = window_text[lo:hi]
        if _name_in_haystack(ctx, names):
            n += 1
    return n


def first_dialogue_snippet_near_character(
    text: str,
    *,
    canonical_name: str,
    variants: list[str],
    max_chars: int = 500,
) -> str | None:
    """Return the first quoted span near a character name, for debugging or UI."""
    names = _names_for_attribution(canonical_name, variants)
    if not names:
        return None
    for start, end in _quote_spans(text):
        lo = max(0, start - 50)
        hi = min(len(text), end + 50)
        ctx = text[lo:hi]
        if _name_in_haystack(ctx, names):
            span = text[start:end]
            if max_chars and len(span) > max_chars:
                return span[:max_chars]
            return span
    return None


# ─── The author's review action ─────────────────────────


ReviewAction = Literal["accept", "adjust", "reject"]


async def set_authoritative_translation(
    session: AsyncSession,
    *,
    voice_id: UUID,
    action: ReviewAction,
    edited_voice_summary: str | None = None,
    edited_translation: str | None = None,
) -> None:
    """Apply the author's review action to a voice profile.

    Three cases:

    - ``accept``: status -> 'accepted'.
      reference_passage_translation_authoritative is set equal to the
      proposed translation. voice_summary is unchanged. ``edited_*``
      args must be None.

    - ``adjust``: status -> 'adjusted'. At least one of
      edited_voice_summary or edited_translation must be provided.
      voice_summary is updated if edited_voice_summary is given;
      translation_authoritative is set to edited_translation if given,
      else to the proposed translation (the author kept the
      translation as-is but changed the summary).

    - ``reject``: status -> 'rejected'.
      translation_authoritative stays NULL. voice_summary unchanged.
      Translation downstream skips this character. ``edited_*`` args
      must be None.

    The proposed translation is NEVER overwritten by this function.
    The model's original output is preserved through any review for
    quality tracking and restoration.
    """
    if action in ("accept", "reject") and (
        edited_voice_summary is not None or edited_translation is not None
    ):
        raise ValueError("accept/reject do not take edited fields.")
    if action == "accept":
        voice = await session.get(CharacterVoice, voice_id)
        if voice is None:
            raise LookupError("voice")
        voice.status = "accepted"
        voice.reference_passage_translation_authoritative = (
            voice.reference_passage_translation_proposed
        )
        await session.commit()
        return
    if action == "reject":
        voice = await session.get(CharacterVoice, voice_id)
        if voice is None:
            raise LookupError("voice")
        voice.status = "rejected"
        voice.reference_passage_translation_authoritative = None
        await session.commit()
        return
    if action == "adjust":
        if edited_voice_summary is None and edited_translation is None:
            raise ValueError("adjust requires at least one edit.")
        voice = await session.get(CharacterVoice, voice_id)
        if voice is None:
            raise LookupError("voice")
        voice.status = "adjusted"
        if edited_voice_summary is not None:
            voice.voice_summary = edited_voice_summary
        if edited_translation is not None:
            voice.reference_passage_translation_authoritative = edited_translation
        else:
            voice.reference_passage_translation_authoritative = (
                voice.reference_passage_translation_proposed
            )
        await session.commit()
        return
    raise ValueError(f"Unknown action: {action}")


# ─── Author review (working voices API) ─────────────────


def _character_voice_to_out(
    voice: CharacterVoice,
    *,
    canonical_name: str,
) -> VoiceWorkingProfileOut:
    return VoiceWorkingProfileOut(
        id=voice.id,
        glossary_entry_id=voice.glossary_entry_id,
        canonical_name=canonical_name,
        voice_summary=voice.voice_summary,
        reference_passage_source=voice.reference_passage_source,
        reference_passage_translation_proposed=voice.reference_passage_translation_proposed,
        reference_passage_translation_authoritative=voice.reference_passage_translation_authoritative,
        status=voice.status,
        dialogue_volume_observed=voice.dialogue_volume_observed,
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
    """Load all character voice rows for the book with glossary names."""
    stmt = (
        select(CharacterVoice, GlossaryEntry.canonical_form)
        .join(GlossaryEntry, GlossaryEntry.id == CharacterVoice.glossary_entry_id)
        .where(CharacterVoice.book_id == book_id)
        .order_by(GlossaryEntry.canonical_form)
    )
    result = await session.execute(stmt)
    entries = [
        _character_voice_to_out(v, canonical_name=canonical)
        for v, canonical in result.all()
    ]
    return WorkingVoicesResponse(entries=entries)


async def patch_working_voice_profile(
    session: AsyncSession,
    *,
    book_id: UUID,
    voice_id: UUID,
    patch: VoiceWorkingProfilePatchIn,
) -> VoiceWorkingProfileOut:
    """Accept, reject, or adjust a voice profile (author review)."""
    voice = await session.get(CharacterVoice, voice_id)
    if voice is None or voice.book_id != book_id:
        raise LookupError("voice")

    entry = await session.get(GlossaryEntry, voice.glossary_entry_id)
    if entry is None:
        raise LookupError("voice")
    canonical_name = entry.canonical_form

    if patch.accept:
        voice.status = "accepted"
        voice.reference_passage_translation_authoritative = (
            voice.reference_passage_translation_proposed
        )
    elif patch.reject:
        voice.status = "rejected"
        voice.reference_passage_translation_authoritative = None
    else:
        # Adjust: at least one of voice_summary / reference_passage_translation
        voice.status = "adjusted"
        if patch.voice_summary is not None:
            voice.voice_summary = patch.voice_summary
        if patch.reference_passage_translation is not None:
            voice.reference_passage_translation_authoritative = (
                patch.reference_passage_translation
            )
        elif patch.voice_summary is not None:
            # Summary-only edit: lock in the model's translation as the sample
            voice.reference_passage_translation_authoritative = (
                voice.reference_passage_translation_proposed
            )

    await session.commit()
    await session.refresh(voice)
    return _character_voice_to_out(voice, canonical_name=canonical_name)


# ─── Top-level orchestration ────────────────────────────


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


async def extract_book_voices(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
) -> None:
    """Full voice-extraction loop for one book.

    Scheduled as a background task. Loads the manuscript and the
    glossary character list once at the start; loops through windows;
    persists each delta; sets the book's voice extraction status as it
    goes.

    Loop shape::

        ok, reason = await can_run_voice_extraction(session, book_id=book_id)
        if not ok:
            mark_voice_status_failed(book_id, reason)
            return

        characters = await load_glossary_characters(session, book_id=book_id)
        windows = make_windows(manuscript_text)
        for n, window in enumerate(windows, start=1):
            current = await load_compact_voice_profiles(session, book_id=book_id)
            previous_notepad = await load_previous_notepad(session, book_id=book_id)
            delta = await extract_voices_window(
                window_text=window,
                glossary_characters=characters,
                current_profiles=current,
                previous_notepad=previous_notepad,
                window_number=n,
                total_windows=len(windows),
                source_language=book.source_language,
                target_language=book.target_language,
                settings=settings,
            )
            await apply_delta(
                session,
                book_id=book_id,
                delta=delta,
                window_text=window,
                window_number=n,
            )

    Notes:

    - Open a session per window, not one for the entire run.
    - Set Langfuse ``session_id=str(book_id)``.
    - The character list snapshot at the start of the run is
      intentional — voice extraction takes minutes; the author
      shouldn't be editing the glossary mid-run, and if they do, the
      snapshot is the right behavior.
    - Errors in a single window flip ``books.voice_extraction_status``
      to 'failed' with the reason and stop the loop. Partial profiles
      are kept; the user can Continue from where it stopped.
    """
    if not settings.GEMINI_API_KEY:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            book = await session.get(Book, book_id)
            if book is not None:
                book.voice_extraction_status = "failed"
                if not continue_extraction:
                    _clear_book_voice_progress_fields(book)
                book.voice_extraction_last_error = "GEMINI_API_KEY is not configured."
            await session.commit()
        log.warning("voice_skipped_no_key", book_id=str(book_id))
        return

    log.info(
        "voice_extraction_task_started",
        book_id=str(book_id),
        continue_extraction=continue_extraction,
    )
    session_factory = get_sessionmaker()
    characters: list[GlossaryCharacterRef] = []
    windows: list[str] = []
    start_window = 1
    total = 0

    try:
        async with session_factory() as session:
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("voice_extraction_book_missing", book_id=str(book_id))
                return
            plaintext = await _load_book_plaintext(session, book_id)
            windows = make_windows(plaintext)
            total = len(windows)

            ok, reason = await can_run_voice_extraction(session, book_id=book_id)
            if not ok:
                book = await session.get(Book, book_id)
                if book is not None:
                    book.voice_extraction_status = "failed"
                    book.voice_extraction_last_error = (reason or "Precondition not met.")[:5000]
                await session.commit()
                return

            if continue_extraction:
                b = await session.get(Book, book_id)
                if b is None:
                    return
                if (
                    b.voice_extraction_windows_total is not None
                    and b.voice_extraction_windows_total != total
                ):
                    b.voice_extraction_status = "failed"
                    b.voice_extraction_last_error = (
                        "Manuscript windowing changed; cannot continue. Start a new extraction."
                    )
                    await session.commit()
                    log.error(
                        "voice_continue_window_mismatch",
                        book_id=str(book_id),
                        had_total=b.voice_extraction_windows_total,
                        new_total=total,
                    )
                    return
                n_done = b.voice_extraction_windows_completed
                n_done = 0 if n_done is None else int(n_done)
                start_window = n_done + 1
            else:
                start_window = 1

            characters = await load_glossary_characters(session, book_id=book_id)
            if not characters:
                book = await session.get(Book, book_id)
                if book is not None:
                    book.voice_extraction_status = "failed"
                    book.voice_extraction_last_error = (
                        "No character entries in the working glossary for this book."
                    )
                await session.commit()
                return

        if total == 0:
            async with session_factory() as session:
                b = await session.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_status = "completed"
                    b.voice_extraction_cancel_requested = False
                    b.voice_extraction_last_error = None
                    _clear_book_voice_progress_fields(b)
                await session.commit()
            log.info("voice_extraction_empty_manuscript", book_id=str(book_id))
            return

        if start_window > total:
            async with session_factory() as session:
                b = await session.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_status = "completed"
                    b.voice_extraction_cancel_requested = False
                    b.voice_extraction_last_error = None
                    _clear_book_voice_progress_fields(b)
                await session.commit()
            log.info(
                "voice_extraction_nothing_left",
                book_id=str(book_id),
            )
            return

        if not continue_extraction:
            async with session_factory() as session:
                b = await session.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_cancel_requested = False
                    b.voice_extraction_windows_total = total
                    b.voice_extraction_windows_completed = 0
                await session.commit()
        else:
            async with session_factory() as session:
                b = await session.get(Book, book_id)
                if b is not None:
                    b.voice_extraction_cancel_requested = False
                    b.voice_extraction_windows_total = total
                await session.commit()

        cancelled = False
        with propagate_attributes(
            session_id=str(book_id),
            trace_name="voice_extraction",
        ):
            for n in range(start_window, total + 1):
                window = windows[n - 1]
                async with session_factory() as session:
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

                    current = await load_compact_voice_profiles(session, book_id=book_id)
                    previous_notepad = await load_previous_notepad(
                        session,
                        book_id=book_id,
                    )
                    delta = await extract_voices_window(
                        window_text=window,
                        glossary_characters=characters,
                        current_profiles=current,
                        previous_notepad=previous_notepad,
                        window_number=n,
                        total_windows=total,
                        source_language=book.source_language,
                        target_language=book.target_language,
                        settings=settings,
                    )
                    await apply_delta(
                        session,
                        book_id=book_id,
                        delta=delta,
                        window_text=window,
                        window_number=n,
                    )
                    book = await session.get(Book, book_id)
                    if book is not None:
                        book.voice_extraction_windows_completed = n
                        book.voice_extraction_last_error = None
                    await session.commit()

                if n % 10 == 0 or n == total:
                    log.info(
                        "voice_extraction_progress",
                        book_id=str(book_id),
                        window=n,
                        total_windows=total,
                    )

        if cancelled:
            log.info("voice_extraction_cancelled", book_id=str(book_id))
            return

        async with session_factory() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.voice_extraction_status = "completed"
                b.voice_extraction_cancel_requested = False
                b.voice_extraction_last_error = None
                _clear_book_voice_progress_fields(b)
            await session.commit()

        log.info("voice_extraction_completed", book_id=str(book_id))

    except GenerationDisabledError:
        async with session_factory() as session:
            bb = await session.get(Book, book_id)
            if bb is not None:
                bb.voice_extraction_status = "failed"
                bb.voice_extraction_last_error = "GEMINI_API_KEY is not configured."
                bb.voice_extraction_cancel_requested = False
            await session.commit()
        log.warning("voice_generation_disabled", book_id=str(book_id))

    except Exception as exc:
        log.exception("voice_extraction_failed", book_id=str(book_id))
        async with session_factory() as session:
            bb = await session.get(Book, book_id)
            if bb is not None:
                bb.voice_extraction_status = "failed"
                bb.voice_extraction_last_error = (str(exc) or type(exc).__name__)[:5000]
                bb.voice_extraction_cancel_requested = False
            await session.commit()
    finally:
        await _reconcile_stuck_running_voice(book_id)
