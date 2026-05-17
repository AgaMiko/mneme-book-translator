"""Speaker-identification service (Pass 1).

Runs before voice extraction. Persists, per manuscript window, which
glossary characters have at least one quoted speaking line. Output is
consumed downstream by Pass 2 (voice extraction) and translation.

Pipeline mirror
---------------
Function names and lifecycle states mirror ``voice_service`` so the
two stages feel symmetric in code and in the UI:
``extract_book_speakers`` runs the per-window loop,
``apply_speakers_delta`` validates and persists,
``_clear_speakers_progress_fields``/``_finalize_speakers_cancelled``/
``reconcile_stale_speakers_runs_on_startup`` handle the same lifecycle
transitions voice does.

Voice extraction internals are NOT touched by this module. The output
table is consumed downstream; the voice extractor's behavior is
unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from langfuse import propagate_attributes
from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, update

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.core.db import get_sessionmaker, rowcount
from app.core.logging import get_logger
from app.generation.chains.identify_speakers_chain import identify_speakers_window
from app.generation.client import GenerationDisabledError
from app.generation.prompt_manager.models.identify_speakers_model import (
    GlossaryCharacterRef,
    SpeakerNote,
    SpeakersInWindow,
)
from app.models.book import Book
from app.models.glossary import GlossaryEntry
from app.models.speakers import SpeakerNotepad, WindowSpeaker
from app.schemas.speakers import (
    CharacterSpeakerMapOut,
    SpeakerWindowOut,
    WorkingSpeakersResponse,
)
from app.services import speakers_validation
from app.services.glossary_service import (
    _load_book_plaintext,
    load_working_glossary_for_latest_run,
)
from app.services.glossary_service import (
    make_windows as glossary_make_windows,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)


# ─── Status helpers ────────────────────────────────────────


def _clear_speakers_progress_fields(book: Book) -> None:
    book.speakers_extraction_windows_total = None
    book.speakers_extraction_windows_completed = None


async def _finalize_speakers_cancelled(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> None:
    b = await session.get(Book, book_id)
    if b is not None:
        b.speakers_extraction_status = "cancelled"
        b.speakers_extraction_cancel_requested = False
    await session.commit()


# ─── Startup housekeeping ──────────────────────────────


_STALE_RUNNING_SPEAKERS_ERROR = (
    "Speaker identification was interrupted (server restarted or deploy). "
    "Use Continue to resume, or Stop/Reset as needed."
)


async def reconcile_stale_speakers_runs_on_startup() -> None:
    """End in-flight ``running`` flags left behind when the process died.

    Background tasks don't survive restarts, but the ``books`` row can
    still show ``speakers_extraction_status == 'running'``, which
    blocks Run and confuses the reader. Mark those as ``failed`` so
    the author can use Continue or Reset.
    """
    log = get_logger(__name__)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        result = await session.execute(
            update(Book)
            .where(Book.speakers_extraction_status == "running")
            .values(
                speakers_extraction_status="failed",
                speakers_extraction_cancel_requested=False,
                speakers_extraction_last_error=_STALE_RUNNING_SPEAKERS_ERROR,
            )
        )
        await session.commit()
        n = rowcount(result)
    if n:
        log.info("reconciled_stale_speakers_runs", count=n)


# ─── Reset ──────────────────────────────────────────────


async def reset_book_speakers_data(
    session: AsyncSession,
    *,
    book: Book,
) -> None:
    """Clear all Pass 1 state for a book — table rows + status fields."""
    await session.execute(delete(SpeakerNotepad).where(SpeakerNotepad.book_id == book.id))
    await session.execute(delete(WindowSpeaker).where(WindowSpeaker.book_id == book.id))
    book.speakers_extraction_status = "idle"
    book.speakers_extraction_cancel_requested = False
    book.speakers_extraction_windows_total = None
    book.speakers_extraction_windows_completed = None
    book.speakers_extraction_last_error = None
    await session.commit()


# ─── Preconditions ──────────────────────────────────────


async def can_run_speakers_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> tuple[bool, str | None]:
    """Returns (True, None) if Pass 1 can run; otherwise (False, reason).

    Same gates as voice: glossary completed AND at least one character
    entry. Voice extraction is gated on speakers downstream; the
    glossary check stays here too because Pass 1 needs the character
    list as its closed candidate set.
    """
    book = await session.get(Book, book_id)
    if book is None:
        return (False, "Book not found.")
    if book.glossary_extraction_status != "completed":
        return (False, "Run glossary extraction first.")

    n = await session.scalar(
        select(func.count())
        .select_from(GlossaryEntry)
        .where(
            GlossaryEntry.book_id == book_id,
            GlossaryEntry.term_type == "character_name",
            GlossaryEntry.status != "rejected",
        )
    )
    if n == 0:
        return (False, "No characters in glossary.")
    return (True, None)


async def can_continue_speakers_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> bool:
    """True when a prior run can resume: same window geometry and unfinished windows."""
    book = await session.get(Book, book_id)
    if book is None or book.speakers_extraction_status == "running":
        return False
    manuscript = await _load_book_plaintext(session, book_id)
    wins = make_windows(manuscript) if manuscript else []
    if not wins:
        return False
    total = len(wins)
    if (
        book.speakers_extraction_windows_total is not None
        and book.speakers_extraction_windows_total != total
    ):
        return False
    done = book.speakers_extraction_windows_completed
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

    Pass 1 uses the same window size as voice extraction so window
    numbers in ``WindowSpeaker`` directly index Pass 2's windows —
    no alignment math.
    """
    return glossary_make_windows(text, window_words=window_words, overlap_words=overlap_words)


# ─── Loading helpers ───────────────────────────────────


async def load_glossary_characters_for_speakers(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[GlossaryCharacterRef]:
    """Load all character glossary entries eligible for Pass 1.

    Distinct from ``voice_service.load_glossary_characters`` — Pass 1
    doesn't carry ``has_voice_profile`` (it's irrelevant to "did this
    character speak in this window?").
    """
    _, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if not entries:
        return []
    out: list[GlossaryCharacterRef] = []
    for e in entries:
        if e.term_type != "character_name" or e.status == "rejected":
            continue
        out.append(
            GlossaryCharacterRef(
                glossary_entry_id=str(e.id),
                canonical_name=e.canonical_form,
                variants=list(e.variants or []),
            )
        )
    return out


async def load_previous_speakers_notepad(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[SpeakerNote]:
    """Load Pass 1's notepad from the end of the previous window."""
    row = await session.get(SpeakerNotepad, book_id)
    if row is None or not row.notes:
        return []
    return TypeAdapter(list[SpeakerNote]).validate_python(list(row.notes))


# ─── Apply / persist ────────────────────────────────────


async def apply_speakers_delta(
    session: AsyncSession,
    *,
    book_id: UUID,
    delta: SpeakersInWindow,
    window_number: int,
    window_text: str,
    glossary_name_by_id: dict[str, str],
) -> None:
    """Persist a window's speakers + update the notepad.

    Cross-checks BOTH the ID/name pairing AND that ``quoted_evidence``
    actually appears in ``window_text`` before persistence; mismatches
    are dropped and logged. Duplicate ``glossary_entry_id`` rows in one
    window are collapsed to the first (unique constraint per window).
    Idempotent on retry: existing rows for
    ``(book_id, window_number)`` are deleted before insert, so this
    window's speaker set is always authoritative on the latest call.

    Caller commits the surrounding transaction.
    """
    kept = speakers_validation.filter_speakers(
        delta.speakers,
        glossary_name_by_id=glossary_name_by_id,
        window_text=window_text,
    )

    await session.execute(
        delete(WindowSpeaker).where(
            WindowSpeaker.book_id == book_id,
            WindowSpeaker.window_number == window_number,
        )
    )
    for s in kept:
        row = WindowSpeaker(
            window_number=window_number,
            quoted_evidence=s.quoted_evidence,
        )
        row.book_id = book_id
        row.glossary_entry_id = UUID(s.glossary_entry_id)
        session.add(row)

    notes_payload = [n.model_dump() for n in delta.notepad]
    notepad = await session.get(SpeakerNotepad, book_id)
    if notepad is None:
        session.add(
            SpeakerNotepad(
                book_id=book_id,
                notes=notes_payload,
                last_window_number=window_number,
            )
        )
    else:
        notepad.notes = notes_payload
        notepad.last_window_number = window_number


# ─── Query helpers (downstream consumers) ───────────────


async def load_speakers_for_window(
    session: AsyncSession,
    *,
    book_id: UUID,
    window_number: int,
) -> list[WindowSpeaker]:
    """Speakers in a specific window. Pass 2 / translation entry point."""
    rows = await session.execute(
        select(WindowSpeaker).where(
            WindowSpeaker.book_id == book_id,
            WindowSpeaker.window_number == window_number,
        )
    )
    return list(rows.scalars().all())


async def load_speakers_for_character(
    session: AsyncSession,
    *,
    book_id: UUID,
    glossary_entry_id: UUID,
) -> list[WindowSpeaker]:
    """All windows where a specific character speaks (ordered)."""
    rows = await session.execute(
        select(WindowSpeaker)
        .where(
            WindowSpeaker.book_id == book_id,
            WindowSpeaker.glossary_entry_id == glossary_entry_id,
        )
        .order_by(WindowSpeaker.window_number)
    )
    return list(rows.scalars().all())


async def speaker_window_counts_by_glossary(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> dict[UUID, int]:
    """Distinct window count per glossary character (Pass 1 map)."""
    rows = await session.execute(
        select(
            WindowSpeaker.glossary_entry_id,
            func.count(WindowSpeaker.window_number),
        )
        .where(WindowSpeaker.book_id == book_id)
        .group_by(WindowSpeaker.glossary_entry_id)
    )
    return {gid: int(n) for gid, n in rows.all()}


async def build_working_speakers_response(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> WorkingSpeakersResponse:
    """Read-only speaker map grouped by character for the review UI."""
    stmt = (
        select(WindowSpeaker, GlossaryEntry)
        .join(GlossaryEntry, GlossaryEntry.id == WindowSpeaker.glossary_entry_id)
        .where(WindowSpeaker.book_id == book_id)
        .order_by(GlossaryEntry.canonical_form.asc(), WindowSpeaker.window_number.asc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return WorkingSpeakersResponse()

    by_character: dict[UUID, CharacterSpeakerMapOut] = {}
    windows_seen: set[int] = set()
    for ws, ge in rows:
        windows_seen.add(ws.window_number)
        entry = by_character.get(ge.id)
        appearance = SpeakerWindowOut(
            window_number=ws.window_number,
            quoted_evidence=ws.quoted_evidence,
        )
        if entry is None:
            by_character[ge.id] = CharacterSpeakerMapOut(
                glossary_entry_id=ge.id,
                canonical_name=ge.canonical_form,
                windows=[ws.window_number],
                appearances=[appearance],
            )
        else:
            entry.windows.append(ws.window_number)
            entry.appearances.append(appearance)

    entries = sorted(
        by_character.values(),
        key=lambda e: (-len(e.windows), e.canonical_name.casefold()),
    )
    return WorkingSpeakersResponse(
        entries=entries,
        windows_mapped=len(windows_seen),
        edges_total=len(rows),
    )


# ─── The extraction loop ────────────────────────────────


async def extract_book_speakers(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
) -> None:
    """Background task: run Pass 1 across every window of a book.

    Mirrors ``voice_service.extract_book_voices`` for lifecycle
    handling (cancel, resume, fail, stale reconciliation) so the two
    stages feel identical to operate.
    """
    if not settings.GEMINI_API_KEY:
        session_local = get_sessionmaker()
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.speakers_extraction_status = "failed"
                b.speakers_extraction_last_error = "GEMINI_API_KEY not configured."
                if not continue_extraction:
                    _clear_speakers_progress_fields(b)
            await session.commit()
        log.warning("speakers_skipped_no_key", book_id=str(book_id))
        return

    session_local = get_sessionmaker()
    try:
        async with session_local() as session:
            plaintext = await _load_book_plaintext(session, book_id)
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("speakers_book_missing", book_id=str(book_id))
                return
            win_list = make_windows(plaintext)
            total = len(win_list)
            if not continue_extraction:
                start_window = 1
            else:
                if (
                    book.speakers_extraction_windows_total is not None
                    and book.speakers_extraction_windows_total != total
                ):
                    book.speakers_extraction_status = "failed"
                    book.speakers_extraction_last_error = (
                        "Manuscript windowing changed; cannot continue. Start a new run."
                    )
                    await session.commit()
                    return
                done = book.speakers_extraction_windows_completed or 0
                start_window = done + 1

        if total == 0:
            async with session_local() as s2:
                b = await s2.get(Book, book_id)
                if b is not None:
                    b.speakers_extraction_status = "completed"
                    b.speakers_extraction_last_error = None
                    b.speakers_extraction_cancel_requested = False
                    _clear_speakers_progress_fields(b)
                await s2.commit()
            log.info("speakers_extraction_empty_manuscript", book_id=str(book_id))
            return

        if start_window > total:
            async with session_local() as s3:
                b = await s3.get(Book, book_id)
                if b is not None:
                    b.speakers_extraction_status = "completed"
                    b.speakers_extraction_last_error = None
                    b.speakers_extraction_cancel_requested = False
                    _clear_speakers_progress_fields(b)
                await s3.commit()
            return

        async with session_local() as s4:
            b0 = await s4.get(Book, book_id)
            if b0 is not None:
                b0.speakers_extraction_cancel_requested = False
                b0.speakers_extraction_windows_total = total
                b0.speakers_extraction_windows_completed = start_window - 1
            await s4.commit()

        cancelled = False
        with propagate_attributes(
            session_id=str(book_id),
            trace_name="speakers_identification",
        ):
            for n in range(start_window, total + 1):
                wtext = win_list[n - 1]
                async with session_local() as session:
                    book = await session.get(Book, book_id)
                    if book is None:
                        raise RuntimeError("book disappeared during speakers extraction")
                    if book.speakers_extraction_cancel_requested:
                        await _finalize_speakers_cancelled(session, book_id=book_id)
                        cancelled = True
                        break
                    characters = await load_glossary_characters_for_speakers(
                        session, book_id=book_id
                    )
                    if not characters:
                        msg = "No character glossary entries available for this book."
                        book.speakers_extraction_status = "failed"
                        book.speakers_extraction_last_error = msg
                        book.speakers_extraction_cancel_requested = False
                        await session.commit()
                        return
                    previous = await load_previous_speakers_notepad(session, book_id=book_id)
                    delta = await identify_speakers_window(
                        window_text=wtext,
                        glossary_characters=characters,
                        previous_notepad=previous,
                        window_number=n,
                        total_windows=total,
                        source_language=book.source_language,
                        settings=settings,
                    )
                    glossary_name_by_id = {
                        c.glossary_entry_id: c.canonical_name for c in characters
                    }
                    await apply_speakers_delta(
                        session,
                        book_id=book_id,
                        delta=delta,
                        window_number=n,
                        window_text=wtext,
                        glossary_name_by_id=glossary_name_by_id,
                    )
                    book.speakers_extraction_windows_completed = n
                    await session.commit()
                if n % 5 == 0 or n == total:
                    log.info(
                        "speakers_extraction_progress",
                        book_id=str(book_id),
                        window=n,
                        total_windows=total,
                    )

        if cancelled:
            return

        async with session_local() as s6:
            b3 = await s6.get(Book, book_id)
            if b3 is not None:
                b3.speakers_extraction_status = "completed"
                b3.speakers_extraction_last_error = None
                b3.speakers_extraction_cancel_requested = False
                _clear_speakers_progress_fields(b3)
            await s6.commit()
        log.info("speakers_extraction_completed", book_id=str(book_id))

    except GenerationDisabledError:
        async with session_local() as session:
            bb = await session.get(Book, book_id)
            if bb is not None:
                bb.speakers_extraction_status = "failed"
                bb.speakers_extraction_last_error = "LLM generation disabled (missing API key)."
                bb.speakers_extraction_cancel_requested = False
            await session.commit()
    except Exception as exc:
        log.exception("speakers_extraction_failed", book_id=str(book_id))
        async with session_local() as session:
            b = await session.get(Book, book_id)
            if b is not None:
                b.speakers_extraction_status = "failed"
                b.speakers_extraction_last_error = (str(exc) or type(exc).__name__)[:5000]
            await session.commit()
