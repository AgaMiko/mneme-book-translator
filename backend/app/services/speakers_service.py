"""Speaker-attribution service (Pass 1).

Runs before voice extraction. Finds every dialogue line of the book
(``dialogue_lines``), cuts the chapters into chunks (``speaker_chunks``)
and asks the model, chunk by chunk, who says each numbered line and to
whom. Every line is stored in ``dialogue_lines``. When the run completes,
``window_speakers`` is rebuilt from the lines, so voice extraction and
translation, which still read speakers per voice-extraction window, keep
working.

Lifecycle (cancel, resume, fail, stale reconciliation) mirrors
``voice_service``. The book's ``speakers_extraction_windows_*`` columns
count chunks.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from langfuse import propagate_attributes
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import aliased, selectinload

from app.constants.voice_extraction import (
    VOICE_EXTRACTION_OVERLAP_WORDS,
    VOICE_EXTRACTION_WINDOW_WORDS,
)
from app.core.db import get_sessionmaker, rowcount
from app.core.logging import get_logger
from app.generation.chains.identify_speakers_chain import identify_speakers_chunk
from app.generation.client import GenerationDisabledError
from app.generation.prompt_manager.models.identify_speakers_model import (
    GlossaryCharacterRef,
)
from app.generation.usage import counting
from app.models.book import Book, Chapter, Paragraph
from app.models.glossary import INACTIVE_STATUSES, GlossaryEntry
from app.models.speakers import DialogueLine, SpeakerNotepad, WindowSpeaker
from app.schemas.speakers import (
    AddresseeCountOut,
    CharacterSpeakerMapOut,
    DialogueLineOut,
    DialogueLinesResponse,
    ManuscriptSpeakerLineOut,
    ManuscriptSpeakersResponse,
    WorkingSpeakersResponse,
)
from app.services import speakers_validation
from app.services.cost_guard import save_state, start_guard
from app.services.dialogue_lines import LineCandidate, find_dialogue_lines
from app.services.fragmenter import ChapterInput, ParagraphInput, count_words
from app.services.glossary_extraction_estimate import glossary_window_count
from app.services.glossary_service import load_working_glossary_for_latest_run
from app.services.speaker_chunks import Chunk, plan_chunks, render_chunk, windows_for_span
from app.services.stages import glossary_ready
from app.services.voice_extraction_estimate import estimate_voice_extraction

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

log = get_logger(__name__)

# Words of evidence kept on a derived ``window_speakers`` row.
_EVIDENCE_WORDS = 15
# Expected cost of a chunk grows with its text and its number of lines;
# one line weighs about as much as this many words of text.
_LINE_WEIGHT_WORDS = 25


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
    await session.execute(delete(DialogueLine).where(DialogueLine.book_id == book.id))
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

    Same gates as voice: glossary usable AND at least one character
    entry. The character list is Pass 1's closed set of speakers.
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


async def can_continue_speakers_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> bool:
    """True when a prior run can resume: same chunk plan and unfinished chunks."""
    book = await session.get(Book, book_id)
    if book is None or book.speakers_extraction_status == "running":
        return False
    plan = await plan_book(session, book_id=book_id)
    total = len(plan.chunks)
    if total == 0:
        return False
    if (
        book.speakers_extraction_windows_total is not None
        and book.speakers_extraction_windows_total != total
    ):
        return False
    done = book.speakers_extraction_windows_completed
    if done is None:
        return False
    return done < total


# ─── Planning ───────────────────────────────────────────


@dataclass(slots=True)
class BookPlan:
    """A book's dialogue lines and Pass 1 chunks, in book order."""

    lines: list[LineCandidate]
    chunks: list[Chunk]
    chapter_labels: dict[UUID, str]
    chapter_positions: dict[UUID, int]
    word_count: int

    @property
    def line_index(self) -> dict[UUID, int]:
        return {ln.paragraph_id: i for i, ln in enumerate(self.lines)}

    @property
    def total_windows(self) -> int:
        """Voice-extraction window count for this text."""
        return glossary_window_count(
            self.word_count,
            window_words=VOICE_EXTRACTION_WINDOW_WORDS,
            overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
        )


def _chapter_label(chapter: Chapter, index: int) -> str:
    # Some titles carry the chapter's epigraph on further lines.
    title = next((ln.strip() for ln in (chapter.title or "").splitlines() if ln.strip()), "")
    return f"chapter {index + 1}" + (f": {title[:80]}" if title else "")


async def plan_book(session: AsyncSession, *, book_id: UUID) -> BookPlan:
    """Load the book's paragraphs and plan lines and chunks (no LLM).

    Only non-empty paragraphs count, as in ``_load_book_plaintext`` and the
    fragmenter, so word offsets line up with windows and fragments.
    """
    book = (
        await session.execute(
            select(Book)
            .where(Book.id == book_id)
            .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
        )
    ).scalar_one_or_none()
    if book is None:
        return BookPlan([], [], {}, {}, 0)
    chapters: list[ChapterInput] = []
    labels: dict[UUID, str] = {}
    positions: dict[UUID, int] = {}
    for index, chapter in enumerate(sorted(book.chapters, key=lambda c: c.position)):
        paras = [
            ParagraphInput(id=p.id, text=p.text)
            for p in sorted(chapter.paragraphs, key=lambda p: p.position)
            if (p.text or "").strip()
        ]
        chapters.append(ChapterInput(id=chapter.id, paragraphs=paras))
        labels[chapter.id] = _chapter_label(chapter, index)
        positions[chapter.id] = index + 1
    lines = find_dialogue_lines(chapters)
    words = sum(count_words(p.text.strip()) for c in chapters for p in c.paragraphs)
    return BookPlan(lines, plan_chunks(chapters, lines), labels, positions, words)


def _expected_cost(total_usd: float, chunks: list[Chunk]) -> Callable[[int], float]:
    """Expected spend after ``k`` chunks; chunks without lines cost nothing."""
    weights = [(c.word_count + _LINE_WEIGHT_WORDS * len(c.lines)) if c.lines else 0 for c in chunks]
    total = sum(weights)
    cumulative = [0]
    for w in weights:
        cumulative.append(cumulative[-1] + w)

    def expected(k: int) -> float:
        k = max(0, min(k, len(chunks)))
        return total_usd * cumulative[k] / total if total else 0.0

    return expected


# ─── Loading helpers ───────────────────────────────────


async def load_glossary_characters_for_speakers(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> list[GlossaryCharacterRef]:
    """Glossary characters eligible as speakers, coded ``C1…Cn`` by name."""
    _, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    chars = sorted(
        (
            e
            for e in entries
            if e.term_type == "character_name" and e.status not in INACTIVE_STATUSES
        ),
        key=lambda e: e.canonical_form.casefold(),
    )
    return [
        GlossaryCharacterRef(
            code=f"C{i}",
            glossary_entry_id=str(e.id),
            canonical_name=e.canonical_form,
            variants=list(e.variants or []),
        )
        for i, e in enumerate(chars, start=1)
    ]


async def _context_labels(
    session: AsyncSession,
    *,
    book_id: UUID,
    paragraph_ids: list[UUID],
) -> dict[UUID, str]:
    """Stored attributions of context paragraphs, as ``"Mira → Stein"``."""
    if not paragraph_ids:
        return {}
    speaker = aliased(GlossaryEntry)
    addressee = aliased(GlossaryEntry)
    rows = (
        await session.execute(
            select(
                DialogueLine.paragraph_id,
                DialogueLine.kind,
                speaker.canonical_form,
                addressee.canonical_form,
            )
            .outerjoin(speaker, speaker.id == DialogueLine.speaker_glossary_entry_id)
            .outerjoin(addressee, addressee.id == DialogueLine.addressee_glossary_entry_id)
            .where(DialogueLine.book_id == book_id, DialogueLine.paragraph_id.in_(paragraph_ids))
        )
    ).all()
    out: dict[UUID, str] = {}
    for pid, kind, who, to in rows:
        if kind == "not_dialogue":
            out[pid] = "not dialogue"
            continue
        label = who or "unknown speaker"
        if kind == "thought":
            label += ", thought"
        if to:
            label += f" → {to}"
        out[pid] = label
    return out


# ─── Persist ────────────────────────────────────────────


async def store_chunk_lines(
    session: AsyncSession,
    *,
    book_id: UUID,
    chunk: Chunk,
    line_by_number: dict[int, LineCandidate],
    resolved: dict[int, speakers_validation.ResolvedLine],
    line_index: dict[UUID, int],
) -> None:
    """Replace the chunk's ``dialogue_lines`` rows. Caller commits.

    Lines without a validated attribution are stored as ``unknown``.
    Idempotent on retry.
    """
    para_ids = [ln.paragraph_id for ln in line_by_number.values()]
    if para_ids:
        await session.execute(
            delete(DialogueLine).where(
                DialogueLine.book_id == book_id,
                DialogueLine.paragraph_id.in_(para_ids),
            )
        )
    for n, line in line_by_number.items():
        r = resolved.get(n)
        row = DialogueLine(
            line_index=line_index[line.paragraph_id],
            chunk_number=chunk.number,
            word_offset=line.word_offset,
            marker=line.marker,
            speech_text=line.speech_text,
            kind=r.kind if r is not None else "unknown",
            speaker_glossary_entry_id=r.speaker_id if r is not None else None,
            addressee_glossary_entry_id=r.addressee_id if r is not None else None,
            confidence=r.confidence if r is not None else None,
            mixed=r.mixed if r is not None else False,
        )
        row.book_id = book_id
        row.paragraph_id = line.paragraph_id
        session.add(row)


async def rebuild_window_speakers(
    session: AsyncSession,
    *,
    book_id: UUID,
    total_windows: int,
) -> int:
    """Derive ``window_speakers`` from stored speech lines. Caller commits.

    A character speaks in every voice-extraction window that overlaps one
    of their speech lines. Returns the number of rows written.
    """
    await session.execute(delete(WindowSpeaker).where(WindowSpeaker.book_id == book_id))
    rows = (
        await session.execute(
            select(DialogueLine)
            .where(
                DialogueLine.book_id == book_id,
                DialogueLine.kind == "speech",
                DialogueLine.speaker_glossary_entry_id.is_not(None),
            )
            .order_by(DialogueLine.line_index)
        )
    ).scalars()
    seen: set[tuple[int, UUID]] = set()
    for line in rows:
        gid = line.speaker_glossary_entry_id
        if gid is None:
            continue
        span = max(1, count_words(line.speech_text))
        for n in windows_for_span(line.word_offset, span, total_windows=total_windows):
            if (n, gid) in seen:
                continue
            seen.add((n, gid))
            ws = WindowSpeaker(
                window_number=n,
                quoted_evidence=" ".join(line.speech_text.split()[:_EVIDENCE_WORDS]),
            )
            ws.book_id = book_id
            ws.glossary_entry_id = gid
            session.add(ws)
    return len(seen)


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
    """Per-character line counts for the review UI, from ``dialogue_lines``.

    ``windows`` per character is computed from the lines with the same
    geometry as ``rebuild_window_speakers``, so it is available while a
    run is still going.
    """
    rows = (
        (
            await session.execute(
                select(DialogueLine)
                .where(DialogueLine.book_id == book_id)
                .order_by(DialogueLine.line_index)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return WorkingSpeakersResponse()

    chapter_rows = await session.execute(
        select(DialogueLine.paragraph_id, Chapter.position)
        .join(Paragraph, Paragraph.id == DialogueLine.paragraph_id)
        .join(Chapter, Chapter.id == Paragraph.chapter_id)
        .where(DialogueLine.book_id == book_id)
    )
    chapter_of = {pid: pos for pid, pos in chapter_rows.all()}
    ids = {
        gid
        for r in rows
        for gid in (r.speaker_glossary_entry_id, r.addressee_glossary_entry_id)
        if gid is not None
    }
    name_rows = await session.execute(
        select(GlossaryEntry.id, GlossaryEntry.canonical_form).where(GlossaryEntry.id.in_(ids))
    )
    names = {gid: name for gid, name in name_rows.all()}
    book = await session.get(Book, book_id)
    word_count = book.word_count if book is not None else 0
    total_windows = glossary_window_count(
        word_count,
        window_words=VOICE_EXTRACTION_WINDOW_WORDS,
        overlap_words=VOICE_EXTRACTION_OVERLAP_WORDS,
    )

    speech: dict[UUID, int] = Counter()
    thoughts: dict[UUID, int] = Counter()
    words: dict[UUID, int] = Counter()
    chapters: dict[UUID, set[int]] = defaultdict(set)
    windows: dict[UUID, set[int]] = defaultdict(set)
    addressees: dict[UUID, Counter[UUID]] = defaultdict(Counter)
    unknown = not_dialogue = 0
    for r in rows:
        gid = r.speaker_glossary_entry_id
        if r.kind == "not_dialogue":
            not_dialogue += 1
            continue
        if gid is None:
            unknown += 1
            continue
        if r.kind == "thought":
            thoughts[gid] += 1
            continue
        speech[gid] += 1
        n_words = count_words(r.speech_text)
        words[gid] += n_words
        chapters[gid].add(chapter_of.get(r.paragraph_id, -1) + 1)
        windows[gid].update(
            windows_for_span(r.word_offset, max(1, n_words), total_windows=total_windows)
        )
        if r.addressee_glossary_entry_id is not None:
            addressees[gid][r.addressee_glossary_entry_id] += 1

    entries = [
        CharacterSpeakerMapOut(
            glossary_entry_id=gid,
            canonical_name=names.get(gid, "Unknown character"),
            line_count=speech[gid],
            thought_count=thoughts[gid],
            speech_words=words[gid],
            chapters=sorted(chapters[gid] - {0}),
            windows=sorted(windows[gid]),
            addressees=[
                AddresseeCountOut(
                    glossary_entry_id=aid,
                    canonical_name=names.get(aid, "Unknown character"),
                    line_count=n,
                )
                for aid, n in addressees[gid].most_common()
            ],
        )
        for gid in set(speech) | set(thoughts)
    ]
    entries.sort(key=lambda e: (-e.line_count, e.canonical_name.casefold()))
    return WorkingSpeakersResponse(
        entries=entries,
        lines_total=len(rows),
        lines_attributed=sum(speech.values()) + sum(thoughts.values()),
        lines_unknown=unknown,
        lines_not_dialogue=not_dialogue,
    )


async def list_dialogue_lines(
    session: AsyncSession,
    *,
    book_id: UUID,
    speaker: UUID | None,
    limit: int = 500,
) -> DialogueLinesResponse:
    """Lines said by ``speaker`` (speech and thoughts), or with no speaker when None.

    "No speaker" covers speech, thought and unknown lines without a
    glossary speaker; ``not_dialogue`` lines are left out.
    """
    speaker_e = aliased(GlossaryEntry)
    addressee_e = aliased(GlossaryEntry)
    stmt = (
        select(
            DialogueLine,
            Paragraph.text,
            Chapter.position,
            Chapter.title,
            speaker_e.canonical_form,
            addressee_e.canonical_form,
        )
        .join(Paragraph, Paragraph.id == DialogueLine.paragraph_id)
        .join(Chapter, Chapter.id == Paragraph.chapter_id)
        .outerjoin(speaker_e, speaker_e.id == DialogueLine.speaker_glossary_entry_id)
        .outerjoin(addressee_e, addressee_e.id == DialogueLine.addressee_glossary_entry_id)
        .where(DialogueLine.book_id == book_id)
        .order_by(DialogueLine.line_index)
    )
    if speaker is None:
        stmt = stmt.where(
            DialogueLine.speaker_glossary_entry_id.is_(None),
            DialogueLine.kind != "not_dialogue",
        )
    else:
        stmt = stmt.where(DialogueLine.speaker_glossary_entry_id == speaker)
    rows = (await session.execute(stmt.limit(limit + 1))).all()
    lines = [
        DialogueLineOut(
            paragraph_id=dl.paragraph_id,
            line_index=dl.line_index,
            chapter_number=pos + 1,
            chapter_title=title,
            text=text,
            kind=dl.kind,
            speaker_name=who,
            addressee_name=to,
            confidence=dl.confidence,
        )
        for dl, text, pos, title, who, to in rows[:limit]
    ]
    return DialogueLinesResponse(lines=lines, truncated=len(rows) > limit)


async def list_manuscript_speakers(
    session: AsyncSession, *, book_id: UUID
) -> ManuscriptSpeakersResponse:
    """Every dialogue line of the book with its speaker, without the text.

    The manuscript already has the paragraphs, so this returns only what
    it needs to mark them. ``not_dialogue`` lines are left out.
    """
    speaker_e = aliased(GlossaryEntry)
    addressee_e = aliased(GlossaryEntry)
    rows = (
        await session.execute(
            select(DialogueLine, speaker_e.canonical_form, addressee_e.canonical_form)
            .outerjoin(speaker_e, speaker_e.id == DialogueLine.speaker_glossary_entry_id)
            .outerjoin(addressee_e, addressee_e.id == DialogueLine.addressee_glossary_entry_id)
            .where(DialogueLine.book_id == book_id, DialogueLine.kind != "not_dialogue")
            .order_by(DialogueLine.line_index)
        )
    ).all()
    return ManuscriptSpeakersResponse(
        lines=[
            ManuscriptSpeakerLineOut(
                paragraph_id=dl.paragraph_id,
                kind=dl.kind,
                speaker_id=dl.speaker_glossary_entry_id,
                speaker_name=who,
                addressee_name=to,
                confidence=dl.confidence,
                mixed=dl.mixed,
            )
            for dl, who, to in rows
        ]
    )


# ─── The attribution loop ───────────────────────────────


async def _finish_speakers(book_id: UUID, *, total_windows: int) -> None:
    session_local = get_sessionmaker()
    async with session_local() as session:
        n = await rebuild_window_speakers(session, book_id=book_id, total_windows=total_windows)
        b = await session.get(Book, book_id)
        if b is not None:
            b.speakers_extraction_status = "completed"
            b.speakers_extraction_last_error = None
            b.speakers_extraction_cancel_requested = False
            _clear_speakers_progress_fields(b)
        await session.commit()
    log.info("speakers_extraction_completed", book_id=str(book_id), window_edges=n)


async def extract_book_speakers(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
    cost_limit: bool = True,
) -> None:
    """Background task: attribute every dialogue line, chunk by chunk.

    Chunks without dialogue lines are skipped without a call. Pauses like
    Stop when the real cost goes more than ``COST_PAUSE_THRESHOLD`` over
    the estimate for the chunks done so far, unless ``cost_limit`` is off
    (see ``app.services.cost_guard``).
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
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("speakers_book_missing", book_id=str(book_id))
                return
            plan = await plan_book(session, book_id=book_id)
            total = len(plan.chunks)
            if not continue_extraction:
                start_chunk = 1
                await session.execute(delete(DialogueLine).where(DialogueLine.book_id == book_id))
                await session.execute(delete(WindowSpeaker).where(WindowSpeaker.book_id == book_id))
                await session.commit()
            else:
                if (
                    book.speakers_extraction_windows_total is not None
                    and book.speakers_extraction_windows_total != total
                ):
                    book.speakers_extraction_status = "failed"
                    book.speakers_extraction_last_error = (
                        "Manuscript changed; cannot continue. Start a new run."
                    )
                    await session.commit()
                    return
                start_chunk = (book.speakers_extraction_windows_completed or 0) + 1

        if total == 0 or start_chunk > total:
            await _finish_speakers(book_id, total_windows=plan.total_windows)
            return

        async with session_local() as s4:
            b0 = await s4.get(Book, book_id)
            if b0 is None:
                raise RuntimeError("book disappeared during speakers extraction")
            characters = await load_glossary_characters_for_speakers(s4, book_id=book_id)
            if not characters:
                b0.speakers_extraction_status = "failed"
                b0.speakers_extraction_last_error = (
                    "No character glossary entries available for this book."
                )
                b0.speakers_extraction_cancel_requested = False
                await s4.commit()
                return
            b0.speakers_extraction_cancel_requested = False
            b0.speakers_extraction_windows_total = total
            b0.speakers_extraction_windows_completed = start_chunk - 1
            pass1 = estimate_voice_extraction(
                word_count=plan.word_count,
                character_count=len(characters),
                settings=settings,
                speaker_chunks=sum(1 for c in plan.chunks if c.lines),
                dialogue_lines=len(plan.lines),
            ).pass1
            guard = start_guard(
                b0,
                "speakers",
                settings=settings,
                expected=_expected_cost(pass1.estimated_cost_usd, plan.chunks),
                units_total=total,
                start_units=start_chunk - 1,
                limit=cost_limit,
                unit_label="part",
            )
            source_language = b0.resolved_source_language
            await s4.commit()

        by_code = {c.code: (UUID(c.glossary_entry_id), c.canonical_name) for c in characters}
        line_index = plan.line_index
        cancelled = False
        with (
            propagate_attributes(session_id=str(book_id), trace_name="speakers_identification"),
            counting(guard.spend),
        ):
            for chunk in plan.chunks[start_chunk - 1 :]:
                async with session_local() as session:
                    book = await session.get(Book, book_id)
                    if book is None:
                        raise RuntimeError("book disappeared during speakers extraction")
                    if book.speakers_extraction_cancel_requested:
                        await _finalize_speakers_cancelled(session, book_id=book_id)
                        cancelled = True
                        break
                    if chunk.lines:
                        labels = await _context_labels(
                            session,
                            book_id=book_id,
                            paragraph_ids=[p.id for p in chunk.context],
                        )
                        text, context, by_number = render_chunk(chunk, context_labels=labels)
                        result = await identify_speakers_chunk(
                            chunk_text=text,
                            context=context,
                            chapter_label=plan.chapter_labels.get(chunk.chapter_id, "chapter"),
                            glossary_characters=characters,
                            chunk_number=chunk.number,
                            total_chunks=total,
                            source_language=source_language,
                            settings=settings,
                        )
                        resolved = speakers_validation.resolve_attributions(
                            result.lines, line_count=len(by_number), characters=by_code
                        )
                        if len(resolved) < len(by_number):
                            log.warning(
                                "speakers_lines_unattributed",
                                book_id=str(book_id),
                                chunk=chunk.number,
                                missing=len(by_number) - len(resolved),
                            )
                        await store_chunk_lines(
                            session,
                            book_id=book_id,
                            chunk=chunk,
                            line_by_number=by_number,
                            resolved=resolved,
                            line_index=line_index,
                        )
                    book.speakers_extraction_windows_completed = chunk.number
                    guard.units_done = chunk.number
                    reason = guard.overrun() if chunk.number < total else None
                    save_state(book, guard)
                    if reason:
                        book.speakers_extraction_cancel_requested = True
                        log.warning(
                            "speakers_extraction_cost_pause", book_id=str(book_id), reason=reason
                        )
                    await session.commit()
                if chunk.number % 5 == 0 or chunk.number == total:
                    log.info(
                        "speakers_extraction_progress",
                        book_id=str(book_id),
                        chunk=chunk.number,
                        total_chunks=total,
                    )

        if cancelled:
            return
        async with session_local() as s5:
            b5 = await s5.get(Book, book_id)
            if b5 is not None:
                save_state(b5, guard)
            await s5.commit()
        await _finish_speakers(book_id, total_windows=plan.total_windows)

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
