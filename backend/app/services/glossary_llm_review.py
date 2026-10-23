"""Decide the remaining pending glossary terms with an LLM, for the author to check.

Runs when the author asks for it (the "Auto-review" button). First, pending
forms of reviewed terms are decided without the LLM
(``glossary_service.apply_form_matches``). The rest go to the model in
batches, each with passages from the book, the accepted terms (to merge
into and as examples) and the author's removed terms (as examples).

Each decision is stored like the form matches: on ``GlossaryEntry.auto_review``
with the model's reason and confidence, so the author can confirm or undo
it. Variants the model calls wrong are removed and put back on undo. A
better English target is only suggested, never applied.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.constants.glossary_taxonomy import normalize_stored_term_type
from app.core.logging import get_logger
from app.generation.chains.review_glossary_chain import review_glossary_batch, review_model
from app.generation.prompt_manager.prompts.review_glossary_prompt import PromptTerm
from app.models.book import Book
from app.services import glossary_service as gs
from app.services.glossary_auto_review import term_forms
from app.services.term_matching import TermIndex, find_terms, fold

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings
    from app.generation.prompt_manager.models.review_glossary_model import TermReview
    from app.models.glossary import GlossaryEntry

log = get_logger(__name__)

BATCH_SIZE = 40
PARALLEL_BATCHES = 3
PASSAGES_PER_TERM = 2
PASSAGE_CHARS = 320
# When this book has few accepted terms, other books' fill the examples up to this.
MIN_ACCEPTED_EXAMPLES = 60


class ReviewConflictError(RuntimeError):
    """Extraction is running, or there is no glossary to review."""


def _target(entry: GlossaryEntry) -> str:
    rec = entry.translation_recommendation or {}
    return str(rec.get("proposed_target") or entry.canonical_form)


def _prompt_term(entry: GlossaryEntry, passages: tuple[str, ...] = ()) -> PromptTerm:
    return PromptTerm(
        id=str(entry.id),
        canonical_form=entry.canonical_form,
        term_type=normalize_stored_term_type(entry.term_type),
        target=_target(entry),
        meaning=entry.meaning,
        variants=tuple(entry.variants or []),
        occurrences=entry.occurrence_count,
        passages=passages,
    )


def find_passages(paragraphs: list[str], pending: list[GlossaryEntry]) -> dict[str, list[str]]:
    """Up to ``PASSAGES_PER_TERM`` short passages per pending term, from different paragraphs."""
    index = TermIndex.build(
        [(str(e.id), e.canonical_form, list(e.variants or [])) for e in pending]
    )
    out: dict[str, list[str]] = {str(e.id): [] for e in pending}
    for para in paragraphs:
        seen: set[str] = set()
        for term_id, start, end in find_terms(para, index):
            found = out[term_id]
            if term_id in seen or len(found) >= PASSAGES_PER_TERM:
                continue
            seen.add(term_id)
            half = (PASSAGE_CHARS - (end - start)) // 2
            lo, hi = max(0, start - half), min(len(para), end + half)
            text = " ".join(para[lo:hi].split())
            found.append(("…" if lo > 0 else "") + text + ("…" if hi < len(para) else ""))
        if all(len(v) >= PASSAGES_PER_TERM for v in out.values()):
            break
    return out


async def _past_decisions(
    session: AsyncSession, *, book_id: UUID, accepted_here: list[GlossaryEntry]
) -> tuple[list[GlossaryEntry], list[GlossaryEntry]]:
    """Other books' author decisions: accepted (only to fill up examples) and removed."""
    known = {fold(e.canonical_form) for e in accepted_here}
    accepted: list[GlossaryEntry] = []
    removed: list[GlossaryEntry] = []
    others = (
        (await session.execute(select(Book).where(Book.id != book_id).order_by(Book.created_at)))
        .scalars()
        .all()
    )
    for other in others:
        _run, rows = await gs.load_working_glossary_for_latest_run(session, book_id=other.id)
        for e in rows:
            if not gs._is_author_reviewed(e) or fold(e.canonical_form) in known:
                continue
            known.add(fold(e.canonical_form))
            (removed if e.status == "rejected" else accepted).append(e)
    room = max(0, MIN_ACCEPTED_EXAMPLES - len(accepted_here))
    return accepted[:room], removed


async def review_pending_terms(
    session: AsyncSession, *, book_id: UUID, settings: Settings
) -> dict[str, int]:
    """Decide every pending term of the book's latest glossary. Returns counts."""
    book = await session.get(Book, book_id)
    if book is None:
        raise LookupError("Book not found")
    if book.glossary_extraction_status == "running":
        raise ReviewConflictError("Wait for glossary extraction to finish.")
    run, _ = await gs.load_working_glossary_for_latest_run(session, book_id=book_id)
    if run is None:
        raise ReviewConflictError("This book has no glossary yet.")

    by_form = await gs.apply_form_matches(session, book_id=book_id, extraction_run_id=run.id)
    await session.commit()
    _run, entries = await gs.load_working_glossary_for_latest_run(session, book_id=book_id)
    # Terms whose automatic decision the author undid stay theirs to decide.
    pending = [e for e in entries if e.status == "proposed" and e.auto_review is None]
    counts = {"by_form": by_form, "accepted": 0, "rejected": 0, "merged": 0, "skipped": 0}
    if not pending:
        return counts

    removed_here = [e for e in entries if e.status == "rejected" and gs._is_author_reviewed(e)]
    accepted_here = [e for e in entries if e.status in ("accepted", "adjusted")]
    accepted_more, removed_other = await _past_decisions(
        session, book_id=book_id, accepted_here=accepted_here
    )
    plaintext = await gs._load_book_plaintext(session, book_id)
    passages = find_passages(plaintext.split("\n\n") if plaintext else [], pending)
    # Close the read transaction: the model calls take a while.
    await session.commit()

    accepted_terms = [_prompt_term(e) for e in accepted_here + accepted_more]
    removed_terms = [_prompt_term(e) for e in removed_here + removed_other]
    gate = asyncio.Semaphore(PARALLEL_BATCHES)

    async def run_batch(batch: list[GlossaryEntry]) -> list[TermReview]:
        async with gate:
            result = await review_glossary_batch(
                pending=[_prompt_term(e, tuple(passages[str(e.id)])) for e in batch],
                accepted=accepted_terms,
                removed=removed_terms,
                source_language=book.source_language,
                target_language=book.target_language,
                settings=settings,
            )
            return result.reviews

    model = review_model(settings)
    applied: dict[str, str] = {}
    # A second pass for terms the model left out or merged into a term that
    # does not exist; whatever is still undecided after it stays pending.
    for _attempt in range(2):
        todo = [e for e in pending if str(e.id) not in applied]
        if not todo:
            break
        batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        results = await asyncio.gather(*(run_batch(b) for b in batches))
        reviews = [r for batch in results for r in batch]
        applied |= await apply_reviews(session, entries=entries, reviews=reviews, model=model)
    await session.commit()
    for action in applied.values():
        counts[action] += 1
    counts["skipped"] = len(pending) - len(applied)
    log.info("glossary_llm_review_done", book_id=str(book_id), model=model, **counts)
    return counts


async def apply_reviews(
    session: AsyncSession,
    *,
    entries: list[GlossaryEntry],
    reviews: list[TermReview],
    model: str,
) -> dict[str, str]:
    """Apply the model's decisions to pending rows. Returns ``{entry_id: count key}``.

    Accepts and rejects go first, then merges, so a merge can follow its
    target if that target was itself merged. A merge into a removed term
    becomes a removal; a merge into an unknown id is skipped (the term
    stays pending).
    """
    by_id = {str(e.id): e for e in entries}
    # The model sometimes writes the term itself where its id belongs.
    by_name = {fold(e.canonical_form): e for e in entries}
    pending_ids = {str(e.id) for e in entries if e.status == "proposed" and e.auto_review is None}
    applied: dict[str, str] = {}
    ordered = sorted(reviews, key=lambda r: r.decision == "merge")
    for r in ordered:
        entry = by_id.get(r.entry_id.strip()) or by_name.get(fold(r.entry_id))
        if entry is None or str(entry.id) not in pending_ids or str(entry.id) in applied:
            continue
        note: dict[str, Any] = {
            "action": r.decision,
            "reason": r.reasoning.strip(),
            "confidence": r.confidence,
            "by": model,
        }
        if r.better_target and r.better_target.strip() != _target(entry):
            note["better_target"] = r.better_target.strip()

        decision = r.decision
        winner: GlossaryEntry | None = None
        if decision == "merge":
            ref = (r.merge_into_id or "").strip()
            winner = by_id.get(ref) or by_name.get(fold(ref))
            if winner is not None:
                winner = await gs._follow_merge(session, winner)
            if winner is None or winner.id == entry.id:
                continue
            if winner.status == "rejected":
                decision = "reject"
                note["action"] = "reject"

        wrong = {v.strip().lower() for v in r.wrong_variants}
        removed = [v for v in entry.variants or [] if v.strip().lower() in wrong]
        if removed:
            entry.variants = [v for v in entry.variants or [] if v not in removed]
            note["removed_variants"] = removed

        if decision == "merge" and winner is not None:
            have = {v.strip().lower() for v in [winner.canonical_form, *(winner.variants or [])]}
            forms = term_forms(entry.canonical_form, list(entry.variants or []))
            added = [f for f in gs._unique_variants(forms) if f.lower() not in have]
            winner.variants = gs._unique_variants(list(winner.variants or []) + added)
            entry.status = "merged"
            entry.merged_into_id = winner.id
            note["added_variants"] = added
            applied[str(entry.id)] = "merged"
        elif decision == "reject":
            entry.status = "rejected"
            applied[str(entry.id)] = "rejected"
        else:
            entry.status = "accepted"
            applied[str(entry.id)] = "accepted"
        entry.auto_review = note
    await session.flush()
    return applied
