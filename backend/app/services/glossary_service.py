"""Glossary service — windowing, LLM deltas, and persistence for extraction runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from langfuse import propagate_attributes
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants.glossary_extraction import (
    GLOSSARY_EXTRACTION_OVERLAP_WORDS,
    GLOSSARY_EXTRACTION_WINDOW_WORDS,
)
from app.constants.glossary_taxonomy import (
    normalize_stored_term_type,
    term_type_select_options,
    translation_suggestion_select_options,
)
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.generation import GenerationDisabledError
from app.generation.chains.extract_glossary_chain import extract_glossary_window
from app.generation.prompt_manager.models.extract_glossary_model import (
    GlossaryEntryCompact,
    GlossaryUpdate,
    NewTerm,
    TranslationRecommendation,
)
from app.models.book import Book, Chapter
from app.models.glossary import (
    GlossaryEntry,
    GlossaryExtractionRun,
    GlossaryNotepad,
    GlossaryWindowGeneration,
)
from app.schemas.glossary import (
    GlossaryRunMetaOut,
    GlossarySelectOptionOut,
    GlossaryWorkingEntryOut,
    GlossaryWorkingEntryPatchIn,
    WorkingGlossaryResponse,
)

if TYPE_CHECKING:
    from app.core.config import Settings

log = get_logger(__name__)


def _clear_book_glossary_progress_fields(book: Book) -> None:
    book.glossary_extraction_windows_total = None
    book.glossary_extraction_windows_completed = None


async def _finalize_glossary_cancelled(
    session: AsyncSession,
    *,
    book_id: UUID,
    run_id: UUID,
) -> None:
    plaintext = await _load_book_plaintext(session, book_id)
    wins = make_windows(plaintext) if plaintext else []
    await recompute_glossary_entry_metrics(
        session,
        book_id=book_id,
        extraction_run_id=run_id,
        plaintext=plaintext or "",
        windows=wins,
    )
    run_row = await session.get(GlossaryExtractionRun, run_id)
    if run_row:
        run_row.status = "cancelled"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.error_message = "Cancelled by user"
    b = await session.get(Book, book_id)
    if b:
        b.glossary_extraction_status = "cancelled"
        b.glossary_extraction_cancel_requested = False
    await session.commit()


# Manuscripts sometimes contain huge space-free runs (URLs, artifacts).
# Without chunking, a single "word" can blow one window to megabytes and
# break structured-output calls on that window only.
_MAX_WORD_CHARS = 512


def _split_manuscript_words(text: str) -> list[str]:
    words: list[str] = []
    for raw in text.split():
        if len(raw) <= _MAX_WORD_CHARS:
            words.append(raw)
            continue
        for i in range(0, len(raw), _MAX_WORD_CHARS):
            words.append(raw[i : i + _MAX_WORD_CHARS])
    return words


def make_windows(
    text: str,
    *,
    window_words: int = GLOSSARY_EXTRACTION_WINDOW_WORDS,
    overlap_words: int = GLOSSARY_EXTRACTION_OVERLAP_WORDS,
) -> list[str]:
    """Split full manuscript text into overlapping word windows."""
    words = _split_manuscript_words(text)
    if not words:
        return []
    if len(words) <= window_words:
        return [" ".join(words)]
    stride = window_words - overlap_words
    windows: list[str] = []
    start = 0
    while start < len(words):
        chunk = words[start : start + window_words]
        windows.append(" ".join(chunk))
        if start + window_words >= len(words):
            break
        start += stride
    return windows


def _unique_variants(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def enrich_glossary_entries_for_review(
    entries: list[GlossaryEntry],
    plaintext: str,
    windows: list[str],
) -> list[GlossaryWorkingEntryOut]:
    """Project ORM rows to API rows with manuscript-wide counts and normalized targets."""
    out: list[GlossaryWorkingEntryOut] = []
    for e in entries:
        rec = _normalize_translation_recommendation(
            e.translation_recommendation or {},
            e.canonical_form,
        )
        variants = list(e.variants or [])
        occ = (
            _count_term_hits(plaintext, e.canonical_form, variants)
            if plaintext
            else e.occurrence_count
        )
        fs = _first_seen_window(windows, e.canonical_form, variants)
        base = GlossaryWorkingEntryOut.model_validate(e)
        patch: dict = {
            "translation_recommendation": rec,
            "occurrence_count": occ,
            "term_type": normalize_stored_term_type(e.term_type),
        }
        if fs is not None:
            patch["first_seen_window"] = fs
        out.append(base.model_copy(update=patch))
    return out


def _working_glossary_taxonomy_payload() -> tuple[
    list[GlossarySelectOptionOut],
    list[GlossarySelectOptionOut],
]:
    tt = [GlossarySelectOptionOut(**x) for x in term_type_select_options()]
    tr = [GlossarySelectOptionOut(**x) for x in translation_suggestion_select_options()]
    return tt, tr


async def build_working_glossary_response(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> WorkingGlossaryResponse:
    """Latest run plus entries, with occurrence / first-seen / targets from full text."""
    term_type_options, translation_suggestion_options = _working_glossary_taxonomy_payload()
    run, entries = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if run is None:
        return WorkingGlossaryResponse(
            run=None,
            entries=[],
            term_type_options=term_type_options,
            translation_suggestion_options=translation_suggestion_options,
        )
    plaintext = await _load_book_plaintext(session, book_id)
    wins = make_windows(plaintext) if plaintext else []
    out_entries = enrich_glossary_entries_for_review(entries, plaintext or "", wins)
    meta = GlossaryRunMetaOut(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        model=run.model,
        entry_count=len(out_entries),
    )
    return WorkingGlossaryResponse(
        run=meta,
        entries=out_entries,
        term_type_options=term_type_options,
        translation_suggestion_options=translation_suggestion_options,
    )


async def load_working_glossary_for_latest_run(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> tuple[GlossaryExtractionRun | None, list[GlossaryEntry]]:
    """Return the most recent extraction run for the book and all its entries.

    Entries are ordered by canonical form for stable scanning. When no run
    exists yet, returns ``(None, [])``.
    """
    run_result = await session.execute(
        select(GlossaryExtractionRun)
        .where(GlossaryExtractionRun.book_id == book_id)
        .order_by(GlossaryExtractionRun.started_at.desc())
        .limit(1),
    )
    run = run_result.scalars().first()
    if run is None:
        return None, []
    ent_result = await session.execute(
        select(GlossaryEntry)
        .where(GlossaryEntry.extraction_run_id == run.id)
        .order_by(GlossaryEntry.canonical_form.asc()),
    )
    return run, list(ent_result.scalars().all())


async def merge_working_glossary_entries(
    session: AsyncSession,
    *,
    book_id: UUID,
    loser_id: UUID,
    winner_id: UUID,
) -> GlossaryWorkingEntryOut:
    """Fold ``loser_id`` into ``winner_id`` (same as an LLM ``merges`` delta)."""

    run, _ = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if run is None:
        raise LookupError("no_run")
    if loser_id == winner_id:
        raise ValueError("Cannot merge an entry into itself.")

    winner = await session.get(GlossaryEntry, winner_id)
    loser = await session.get(GlossaryEntry, loser_id)
    if winner is None or loser is None:
        raise LookupError("entry")
    if (
        winner.book_id != book_id
        or loser.book_id != book_id
        or winner.extraction_run_id != run.id
        or loser.extraction_run_id != run.id
    ):
        raise LookupError("entry")
    if winner.status == "rejected" or loser.status == "rejected":
        raise ValueError(
            "Merge is only available between non-rejected entries.",
        )

    w_var = list(winner.variants or [])
    l_var = list(loser.variants or [])
    winner.variants = _unique_variants(
        w_var + l_var + [loser.canonical_form],
    )
    await session.delete(loser)
    await session.commit()
    await session.refresh(winner)

    plaintext = await _load_book_plaintext(session, book_id)
    wins = make_windows(plaintext) if plaintext else []
    enriched = enrich_glossary_entries_for_review([winner], plaintext or "", wins)
    log.info(
        "glossary_author_merge",
        book_id=str(book_id),
        winner_id=str(winner_id),
        loser_id=str(loser_id),
        extraction_run_id=str(run.id),
    )
    return enriched[0]


async def patch_working_glossary_entry(
    session: AsyncSession,
    *,
    book_id: UUID,
    entry_id: UUID,
    patch: GlossaryWorkingEntryPatchIn,
) -> GlossaryWorkingEntryOut:
    """Update translation fields and/or acceptance on one row of the latest run."""

    run, _ = await load_working_glossary_for_latest_run(session, book_id=book_id)
    if run is None:
        raise LookupError("no_run")

    entry = await session.get(GlossaryEntry, entry_id)
    if entry is None or entry.book_id != book_id or entry.extraction_run_id != run.id:
        raise LookupError("entry")

    if patch.merge_into_entry_id is not None:
        return await merge_working_glossary_entries(
            session,
            book_id=book_id,
            loser_id=entry_id,
            winner_id=patch.merge_into_entry_id,
        )

    if patch.reject:
        entry.status = "rejected"
        await session.commit()
        await session.refresh(entry)
        plaintext = await _load_book_plaintext(session, book_id)
        wins = make_windows(plaintext) if plaintext else []
        enriched = enrich_glossary_entries_for_review([entry], plaintext or "", wins)
        log.info(
            "glossary_author_reject",
            book_id=str(book_id),
            entry_id=str(entry_id),
            extraction_run_id=str(run.id),
        )
        return enriched[0]

    raw = dict(entry.translation_recommendation or {})
    if patch.proposed_target is not None:
        raw["proposed_target"] = patch.proposed_target
    if patch.suggestion is not None:
        raw["suggestion"] = patch.suggestion

    if patch.proposed_target is not None or patch.suggestion is not None:
        try:
            tr = TranslationRecommendation.model_validate(raw)
        except ValidationError as exc:
            msg = "; ".join(
                f"{'.'.join(str(x) for x in err.get('loc', ()))}: {err.get('msg', 'invalid')}"
                for err in exc.errors()
            )
            raise ValueError(msg) from exc
        entry.translation_recommendation = tr.model_dump(mode="json")

    if patch.accept:
        entry.status = "accepted"
    elif patch.proposed_target is not None or patch.suggestion is not None:
        if entry.status in ("proposed", "accepted", "adjusted", "rejected"):
            entry.status = "adjusted"

    await session.commit()
    await session.refresh(entry)

    plaintext = await _load_book_plaintext(session, book_id)
    wins = make_windows(plaintext) if plaintext else []
    enriched = enrich_glossary_entries_for_review([entry], plaintext or "", wins)
    return enriched[0]


async def _max_stored_glossary_window(
    session: AsyncSession,
    *,
    extraction_run_id: UUID,
) -> int:
    m = await session.execute(
        select(func.max(GlossaryWindowGeneration.window_number)).where(
            GlossaryWindowGeneration.extraction_run_id == extraction_run_id,
        ),
    )
    v = m.scalar()
    return int(v) if v is not None else 0


async def _latest_resumable_glossary_run(
    session: AsyncSession,
    book_id: UUID,
) -> GlossaryExtractionRun | None:
    r = await session.execute(
        select(GlossaryExtractionRun)
        .where(
            GlossaryExtractionRun.book_id == book_id,
            GlossaryExtractionRun.status.in_(("failed", "cancelled")),
        )
        .order_by(GlossaryExtractionRun.started_at.desc())
        .limit(1),
    )
    return r.scalars().first()


async def can_continue_glossary_extraction(
    session: AsyncSession,
    *,
    book_id: UUID,
) -> bool:
    """True when the latest failed / cancelled run has at least one window left to process."""
    run = await _latest_resumable_glossary_run(session, book_id)
    if run is None:
        return False
    book = await session.get(Book, book_id)
    if book is None:
        return False
    manuscript = await _load_book_plaintext(session, book_id)
    wins = make_windows(manuscript) if manuscript else []
    if not wins:
        return False
    total = len(wins)
    done = await _max_stored_glossary_window(session, extraction_run_id=run.id)
    if done >= total:
        return False
    if (
        book.glossary_extraction_windows_total is not None
        and book.glossary_extraction_windows_total != total
    ):
        return False
    return True


def _dedupe_new_terms_in_delta(entries: list[NewTerm]) -> list[NewTerm]:
    """Fold duplicate ``canonical_form`` in one LLM delta; merge variant lists."""
    merged: dict[str, NewTerm] = {}
    order: list[str] = []
    for nt in entries:
        c = nt.canonical_form
        if c not in merged:
            merged[c] = nt
            order.append(c)
            continue
        prev = merged[c]
        merged[c] = prev.model_copy(
            update={
                "variants": _unique_variants(list(prev.variants) + list(nt.variants)),
            },
        )
    return [merged[k] for k in order]


def _count_term_hits(window_text: str, canonical: str, variants: list[str]) -> int:
    """Count substring hits for the canonical form and variants (case-insensitive).

    Each distinct surface form (by case-fold) is counted once per pass so
    canonical and a duplicate variant do not inflate totals.
    """
    hay = window_text.lower()
    total = 0
    seen_lower: set[str] = set()
    for raw in [canonical, *variants]:
        t = raw.strip()
        if not t:
            continue
        key = t.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        total += hay.count(key)
    return total


def _first_seen_window(
    windows: list[str],
    canonical: str,
    variants: list[str],
) -> int | None:
    """1-based window index of the first pass where the term appears, or ``None``."""
    for i, w in enumerate(windows, start=1):
        if _count_term_hits(w, canonical, variants) > 0:
            return i
    return None


def _normalize_translation_recommendation(rec: dict, canonical_form: str) -> dict:
    """Ensure ``proposed_target`` is always a concrete string for review UIs."""
    out = dict(rec) if isinstance(rec, dict) else {}
    suggestion = out.get("suggestion")
    if not isinstance(suggestion, str) or not suggestion.strip():
        suggestion = "keep_original"
    out["suggestion"] = suggestion
    pt = out.get("proposed_target")
    if pt is None or (isinstance(pt, str) and not pt.strip()):
        out["proposed_target"] = canonical_form
        rationale = out.get("rationale")
        rat_str = rationale.strip() if isinstance(rationale, str) else ""
        note = (
            "Provisional rendering uses the source form until you set an explicit English target."
        )
        out["rationale"] = f"{rat_str} {note}".strip() if rat_str else note
    raw_alts = out.get("alternative_targets")
    if not isinstance(raw_alts, list):
        raw_alts = []
    pt_key = str(out.get("proposed_target") or "").strip().lower()
    seen: set[str] = {pt_key} if pt_key else set()
    alts: list[str] = []
    for x in raw_alts:
        if not isinstance(x, str):
            continue
        s = x.strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        alts.append(s)
        if len(alts) >= 5:
            break
    out["alternative_targets"] = alts
    return out


async def recompute_glossary_entry_metrics(
    session: AsyncSession,
    *,
    book_id: UUID,
    extraction_run_id: UUID,
    plaintext: str,
    windows: list[str],
) -> None:
    """After a run (or cancel), set occurrence and first-seen from the full manuscript.

    Also normalizes translation JSON so ``proposed_target`` is never empty.
    """
    stmt = select(GlossaryEntry).where(
        GlossaryEntry.extraction_run_id == extraction_run_id,
        GlossaryEntry.book_id == book_id,
    )
    entries = (await session.execute(stmt)).scalars().all()
    for entry in entries:
        variants = list(entry.variants or [])
        entry.occurrence_count = _count_term_hits(plaintext, entry.canonical_form, variants)
        fs = _first_seen_window(windows, entry.canonical_form, variants)
        if fs is not None:
            entry.first_seen_window = fs
        entry.translation_recommendation = _normalize_translation_recommendation(
            entry.translation_recommendation or {},
            entry.canonical_form,
        )
    await session.flush()


async def _load_book_plaintext(session: AsyncSession, book_id: UUID) -> str:
    stmt = (
        select(Book)
        .where(Book.id == book_id)
        .options(selectinload(Book.chapters).selectinload(Chapter.paragraphs))
    )
    book = (await session.execute(stmt)).scalar_one_or_none()
    if book is None:
        return ""
    parts: list[str] = []
    for chapter in sorted(book.chapters, key=lambda c: c.position):
        for para in sorted(chapter.paragraphs, key=lambda p: p.position):
            t = (para.text or "").strip()
            if t:
                parts.append(t)
    return "\n\n".join(parts)


async def load_compact_glossary(
    session: AsyncSession,
    *,
    extraction_run_id: UUID,
) -> list[GlossaryEntryCompact]:
    stmt = select(GlossaryEntry).where(
        GlossaryEntry.extraction_run_id == extraction_run_id,
        GlossaryEntry.status != "rejected",
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[GlossaryEntryCompact] = []
    for e in rows:
        rec = e.translation_recommendation or {}
        suggestion = rec.get("suggestion", "translate")
        raw_alts = rec.get("alternative_targets")
        alts: list[str] = []
        if isinstance(raw_alts, list):
            for x in raw_alts:
                if isinstance(x, str) and x.strip():
                    alts.append(x.strip())
            alts = alts[:5]
        out.append(
            GlossaryEntryCompact(
                id=str(e.id),
                canonical_form=e.canonical_form,
                variants=list(e.variants or []),
                term_type=normalize_stored_term_type(e.term_type),  # type: ignore[arg-type]
                meaning=e.meaning,
                translation_suggestion=suggestion,  # type: ignore[arg-type]
                alternative_targets=alts,
            ),
        )
    return out


def _hydrate_notepad_from_json(notes: list) -> list[str]:
    """Persisted JSON → prompt strings (max three; legacy rows used ``content``)."""
    out: list[str] = []
    for item in notes:
        match item:
            case str(s):
                t = s.strip()
                if t:
                    out.append(t)
            case {"content": str(s)}:
                t = s.strip()
                if t:
                    out.append(t)
            case _:
                pass
        if len(out) >= 3:
            break
    return out


async def load_previous_notepad(
    session: AsyncSession,
    *,
    extraction_run_id: UUID,
) -> list[str]:
    row = await session.get(GlossaryNotepad, extraction_run_id)
    if row is None or not row.notes:
        return []
    return _hydrate_notepad_from_json(row.notes)


async def apply_delta(
    session: AsyncSession,
    *,
    book_id: UUID,
    extraction_run_id: UUID,
    delta: GlossaryUpdate,
    window_text: str,
    window_number: int,
) -> None:
    """Persist one window's delta (merges → refinements → extensions → new → notepad → counts)."""
    for m in delta.merges:
        winner = await session.get(GlossaryEntry, UUID(m.winner_id))
        loser = await session.get(GlossaryEntry, UUID(m.loser_id))
        if winner is None or loser is None:
            raise ValueError("merge references unknown entry id")
        if (
            winner.extraction_run_id != extraction_run_id
            or loser.extraction_run_id != extraction_run_id
        ):
            raise ValueError("merge entries do not belong to this extraction run")
        w_var = list(winner.variants or [])
        l_var = list(loser.variants or [])
        winner.variants = _unique_variants(
            w_var + l_var + [loser.canonical_form],
        )
        await session.delete(loser)

    await session.flush()

    for r in delta.refinements:
        entry = await session.get(GlossaryEntry, UUID(r.entry_id))
        if entry is None or entry.extraction_run_id != extraction_run_id:
            continue

        # Renaming onto an existing canonical would violate ``uq_glossary_run_canonical``.
        # Treat that as an implicit merge (same outcome the model would get from ``merges``).
        if r.new_canonical_form is not None and r.new_canonical_form != entry.canonical_form:
            stmt = select(GlossaryEntry).where(
                GlossaryEntry.extraction_run_id == extraction_run_id,
                GlossaryEntry.canonical_form == r.new_canonical_form,
                GlossaryEntry.id != entry.id,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                existing.variants = _unique_variants(
                    list(existing.variants or [])
                    + list(entry.variants or [])
                    + [entry.canonical_form],
                )
                if r.new_term_type is not None:
                    existing.term_type = r.new_term_type
                if r.new_meaning is not None:
                    existing.meaning = r.new_meaning
                if r.new_translation_recommendation is not None:
                    existing.translation_recommendation = (
                        r.new_translation_recommendation.model_dump(mode="json")
                    )
                await session.delete(entry)
                log.info(
                    "glossary_refinement_canonical_merged_into_existing",
                    extraction_run_id=str(extraction_run_id),
                    window_number=window_number,
                    kept_id=str(existing.id),
                    removed_id=str(entry.id),
                    canonical_form=r.new_canonical_form,
                )
                continue

        if r.new_canonical_form is not None:
            entry.canonical_form = r.new_canonical_form
        if r.new_term_type is not None:
            entry.term_type = r.new_term_type
        if r.new_meaning is not None:
            entry.meaning = r.new_meaning
        if r.new_translation_recommendation is not None:
            entry.translation_recommendation = r.new_translation_recommendation.model_dump(
                mode="json",
            )

    await session.flush()

    for ext in delta.extensions:
        entry = await session.get(GlossaryEntry, UUID(ext.entry_id))
        if entry is None or entry.extraction_run_id != extraction_run_id:
            continue
        cur = list(entry.variants or [])
        entry.variants = _unique_variants(cur + ext.new_variants)

    await session.flush()

    for nt in _dedupe_new_terms_in_delta(delta.new_entries):
        existing = (
            await session.execute(
                select(GlossaryEntry).where(
                    GlossaryEntry.extraction_run_id == extraction_run_id,
                    GlossaryEntry.canonical_form == nt.canonical_form,
                ),
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.variants = _unique_variants(
                list(existing.variants or []) + list(nt.variants),
            )
            log.info(
                "glossary_new_entry_skipped_duplicate_canonical",
                canonical_form=nt.canonical_form,
                window_number=window_number,
                extraction_run_id=str(extraction_run_id),
            )
            continue
        session.add(
            GlossaryEntry(
                book_id=book_id,
                extraction_run_id=extraction_run_id,
                canonical_form=nt.canonical_form,
                term_type=nt.term_type,
                meaning=nt.meaning,
                translation_recommendation=nt.translation_recommendation.model_dump(mode="json"),
                variants=_unique_variants(nt.variants),
                status="proposed",
                first_seen_window=window_number,
                occurrence_count=0,
            ),
        )

    await session.flush()

    notes_payload = list(delta.notepad)
    notepad_row = await session.get(GlossaryNotepad, extraction_run_id)
    if notepad_row is None:
        session.add(
            GlossaryNotepad(
                extraction_run_id=extraction_run_id,
                notes=notes_payload,
                last_window_number=window_number,
            ),
        )
    else:
        notepad_row.notes = notes_payload
        notepad_row.last_window_number = window_number

    await session.flush()


async def extract_book_glossary(
    *,
    book_id: UUID,
    settings: Settings,
    continue_extraction: bool = False,
) -> None:
    """Background task: run glossary windows for a book, optionally resuming a run.

    New run processes every window. With ``continue_extraction=True``, reuses
    the latest *failed* or *cancelled* run and all persisted entries, and only
    runs windows after the last stored ``GlossaryWindowGeneration``. Last-known
    window progress remains on the book if extraction fails.
    """
    if not settings.GEMINI_API_KEY:
        SessionLocal = get_sessionmaker()
        async with SessionLocal() as session:
            book = await session.get(Book, book_id)
            if book is not None:
                book.glossary_extraction_status = "failed"
                if not continue_extraction:
                    _clear_book_glossary_progress_fields(book)
                await session.commit()
        log.warning("glossary_skipped_no_key", book_id=str(book_id))
        return

    SessionLocal = get_sessionmaker()
    run_id: UUID | None = None
    windows: list[str] = []
    start_window = 1

    try:
        async with SessionLocal() as session:
            plaintext = await _load_book_plaintext(session, book_id)
            book = await session.get(Book, book_id)
            if book is None:
                log.warning("glossary_book_missing", book_id=str(book_id))
                return

            windows = make_windows(plaintext)
            total = len(windows)

            if not continue_extraction:
                run = GlossaryExtractionRun(
                    book_id=book_id,
                    status="running",
                    model=settings.GEMINI_MODEL,
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                run_id = run.id
                start_window = 1
            else:
                res = await _latest_resumable_glossary_run(session, book_id)
                if res is None:
                    log.warning("glossary_continue_no_resumable_run", book_id=str(book_id))
                    if book:
                        book.glossary_extraction_status = "failed"
                    await session.commit()
                    return
                run_id = res.id
                if (
                    book.glossary_extraction_windows_total is not None
                    and book.glossary_extraction_windows_total != total
                ):
                    res.error_message = (
                        "Manuscript windowing changed; cannot continue. Start a new extraction."
                    )
                    if book:
                        book.glossary_extraction_status = "failed"
                    await session.commit()
                    log.error(
                        "glossary_continue_window_mismatch",
                        book_id=str(book_id),
                        run_id=str(res.id),
                        had_total=book.glossary_extraction_windows_total,
                        new_total=total,
                    )
                    return
                max_stored = await _max_stored_glossary_window(session, extraction_run_id=run_id)
                start_window = max_stored + 1
                res.status = "running"
                res.model = res.model or settings.GEMINI_MODEL
                res.error_message = None
                await session.commit()
                log.info(
                    "glossary_extraction_resuming",
                    book_id=str(book_id),
                    run_id=str(run_id),
                    from_window=start_window,
                    total_windows=total,
                )

        if run_id is None:
            return

        total = len(windows)
        if total == 0:
            async with SessionLocal() as session:
                run_row = await session.get(GlossaryExtractionRun, run_id)
                if run_row:
                    run_row.status = "completed"
                    run_row.completed_at = datetime.now(timezone.utc)
                b = await session.get(Book, book_id)
                if b:
                    b.glossary_extraction_status = "completed"
                    b.glossary_extraction_cancel_requested = False
                    _clear_book_glossary_progress_fields(b)
                await session.commit()
            log.info("glossary_extraction_empty_manuscript", book_id=str(book_id))
            return

        if start_window > total:
            async with SessionLocal() as session:
                run_row = await session.get(GlossaryExtractionRun, run_id)
                if run_row:
                    run_row.status = "completed"
                    run_row.completed_at = datetime.now(timezone.utc)
                b = await session.get(Book, book_id)
                if b:
                    b.glossary_extraction_status = "completed"
                    b.glossary_extraction_cancel_requested = False
                    _clear_book_glossary_progress_fields(b)
                await session.commit()
            log.info(
                "glossary_extraction_nothing_left_to_process",
                book_id=str(book_id),
                run_id=str(run_id),
            )
            return

        async with SessionLocal() as session:
            b0 = await session.get(Book, book_id)
            if b0:
                b0.glossary_extraction_cancel_requested = False
                b0.glossary_extraction_windows_total = total
                b0.glossary_extraction_windows_completed = start_window - 1
            await session.commit()

        cancelled = False
        with propagate_attributes(
            session_id=str(book_id),
            trace_name="glossary_extraction",
        ):
            for n in range(start_window, total + 1):
                window = windows[n - 1]
                async with SessionLocal() as session:
                    book = await session.get(Book, book_id)
                    if book is None:
                        raise RuntimeError("book disappeared during glossary extraction")
                    if book.glossary_extraction_cancel_requested:
                        await _finalize_glossary_cancelled(
                            session,
                            book_id=book_id,
                            run_id=run_id,
                        )
                        cancelled = True
                        break

                    current = await load_compact_glossary(session, extraction_run_id=run_id)
                    previous_notepad = await load_previous_notepad(
                        session, extraction_run_id=run_id
                    )

                    delta = await extract_glossary_window(
                        window_text=window,
                        current_glossary=current,
                        previous_notepad=previous_notepad,
                        window_number=n,
                        total_windows=total,
                        source_language=book.source_language,
                        target_language=book.target_language,
                        settings=settings,
                    )

                    raw = delta.model_dump(mode="json")
                    session.add(
                        GlossaryWindowGeneration(
                            extraction_run_id=run_id,
                            window_number=n,
                            raw_response=raw,
                        ),
                    )
                    await apply_delta(
                        session,
                        book_id=book_id,
                        extraction_run_id=run_id,
                        delta=delta,
                        window_text=window,
                        window_number=n,
                    )
                    book.glossary_extraction_windows_completed = n
                    await session.commit()

                if n % 10 == 0 or n == total:
                    log.info(
                        "glossary_extraction_progress",
                        book_id=str(book_id),
                        run_id=str(run_id),
                        window=n,
                        total_windows=total,
                    )

        if cancelled:
            log.info("glossary_extraction_cancelled", book_id=str(book_id), run_id=str(run_id))
            return

        async with SessionLocal() as session:
            plaintext = await _load_book_plaintext(session, book_id)
            wins = make_windows(plaintext) if plaintext else []
            await recompute_glossary_entry_metrics(
                session,
                book_id=book_id,
                extraction_run_id=run_id,
                plaintext=plaintext or "",
                windows=wins,
            )
            run_row = await session.get(GlossaryExtractionRun, run_id)
            if run_row:
                run_row.status = "completed"
                run_row.completed_at = datetime.now(timezone.utc)
            b = await session.get(Book, book_id)
            if b:
                b.glossary_extraction_status = "completed"
                b.glossary_extraction_cancel_requested = False
                _clear_book_glossary_progress_fields(b)
            await session.commit()

        log.info("glossary_extraction_completed", book_id=str(book_id), run_id=str(run_id))

    except GenerationDisabledError:
        async with SessionLocal() as session:
            if run_id:
                rr = await session.get(GlossaryExtractionRun, run_id)
                if rr:
                    rr.status = "failed"
                    rr.error_message = "GEMINI_API_KEY not configured"
            bb = await session.get(Book, book_id)
            if bb:
                bb.glossary_extraction_status = "failed"
                bb.glossary_extraction_cancel_requested = False
            await session.commit()
        log.warning("glossary_generation_disabled", book_id=str(book_id))

    except Exception as exc:
        log.exception("glossary_extraction_failed", book_id=str(book_id), run_id=str(run_id))
        async with SessionLocal() as session:
            if run_id:
                plaintext = await _load_book_plaintext(session, book_id)
                wins = make_windows(plaintext) if plaintext else []
                if wins:
                    try:
                        await recompute_glossary_entry_metrics(
                            session,
                            book_id=book_id,
                            extraction_run_id=run_id,
                            plaintext=plaintext,
                            windows=wins,
                        )
                    except Exception:
                        log.warning(
                            "glossary_recompute_after_failed_skipped",
                            book_id=str(book_id),
                            run_id=str(run_id),
                            exc_info=True,
                        )
                rr = await session.get(GlossaryExtractionRun, run_id)
                if rr:
                    rr.status = "failed"
                    rr.error_message = (str(exc) or type(exc).__name__)[:5000]
            bb = await session.get(Book, book_id)
            if bb:
                bb.glossary_extraction_status = "failed"
                bb.glossary_extraction_cancel_requested = False
            await session.commit()


async def publish_final_glossary(
    session: AsyncSession,
    *,
    book_id: UUID,
    extraction_run_id: UUID,
    label: str = "default",
) -> UUID:
    """Freeze reviewed working rows into ``FinalGlossary`` for downstream translation."""
    raise NotImplementedError(
        "INSERT FinalGlossary(book_id, source_extraction_run_id, label); "
        "INSERT FinalGlossaryEntry rows from accepted/adjusted GlossaryEntry; "
        "UPDATE books SET active_final_glossary_id = ... WHERE id = book_id."
    )
