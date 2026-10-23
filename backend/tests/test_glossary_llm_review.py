"""Tests for applying LLM glossary review decisions (no model calls)."""

from typing import Any
from uuid import uuid4

from app.generation.prompt_manager.models.review_glossary_model import TermReview
from app.models.glossary import GlossaryEntry
from app.services.glossary_llm_review import apply_reviews, find_passages


def _entry(canonical: str, status: str = "proposed", variants=None) -> GlossaryEntry:  # type: ignore[no-untyped-def]
    e = GlossaryEntry(
        book_id=uuid4(),
        extraction_run_id=uuid4(),
        canonical_form=canonical,
        term_type="lore_term",
        meaning="",
        translation_recommendation={"suggestion": "translate", "proposed_target": canonical},
        first_seen_window=1,
        variants=variants or [],
        status=status,
    )
    e.id = uuid4()
    return e


class _Session:
    def __init__(self, entries: list[GlossaryEntry]) -> None:
        self.by_id = {e.id: e for e in entries}

    async def get(self, _model: Any, key: Any) -> GlossaryEntry | None:
        return self.by_id.get(key)

    async def flush(self) -> None:
        pass


def _review(entry: GlossaryEntry, decision: str, **kw: Any) -> TermReview:
    return TermReview(
        entry_id=str(entry.id),
        reasoning="Because.",
        decision=decision,  # type: ignore[arg-type]
        confidence=kw.pop("confidence", "high"),
        **kw,
    )


def test_passages_come_from_different_paragraphs_and_case_forms() -> None:
    term = _entry("Wtórne Stworzenie")
    paragraphs = [
        "Nic tu nie ma.",
        "Zakazano Wtórnego Stworzenia dawno temu.",
        "Wtórne Stworzenie to herezja. Wtórne Stworzenie!",
        "O Wtórnym Stworzeniu nie mówiono.",
    ]
    [found] = find_passages(paragraphs, [term]).values()
    assert found == [
        "Zakazano Wtórnego Stworzenia dawno temu.",
        "Wtórne Stworzenie to herezja. Wtórne Stworzenie!",
    ]


async def test_accept_reject_and_suggestions_are_recorded() -> None:
    keep, drop = _entry("Dwoisty"), _entry("łyżka aptekarska")
    herb = _entry("bylica", variants=["bylica", "Hanka"])
    entries = [keep, drop, herb]
    applied = await apply_reviews(
        _Session(entries),  # type: ignore[arg-type]
        entries=entries,
        reviews=[
            _review(keep, "accept"),
            _review(drop, "reject", confidence="low"),
            _review(herb, "accept", wrong_variants=["Hanka"], better_target="mugwort"),
        ],
        model="m",
    )
    assert applied == {str(keep.id): "accepted", str(drop.id): "rejected", str(herb.id): "accepted"}
    assert drop.auto_review == {
        "action": "reject",
        "reason": "Because.",
        "confidence": "low",
        "by": "m",
    }
    assert herb.variants == ["bylica"]
    assert herb.auto_review is not None
    assert herb.auto_review["removed_variants"] == ["Hanka"]
    assert herb.auto_review["better_target"] == "mugwort"


async def test_merge_moves_forms_and_follows_removed_targets() -> None:
    accepted = _entry("Jenna", status="accepted")
    nickname = _entry("Jen", variants=["Jenką", "prosiątkiem"])
    removed = _entry("Strategie Obronne", status="rejected")
    title = _entry("Strategii Obronnych")
    entries = [accepted, nickname, removed, title]
    applied = await apply_reviews(
        _Session(entries),  # type: ignore[arg-type]
        entries=entries,
        reviews=[
            _review(nickname, "merge", merge_into_id=str(accepted.id)),
            _review(title, "merge", merge_into_id=str(removed.id)),
        ],
        model="m",
    )
    assert applied == {str(nickname.id): "merged", str(title.id): "rejected"}
    assert nickname.status == "merged"
    assert nickname.merged_into_id == accepted.id
    # The nickname is not a form of "Jen", so it stays behind.
    assert accepted.variants == ["Jen", "Jenką"]
    assert title.status == "rejected"


async def test_unknown_ids_and_reviewed_rows_are_left_alone() -> None:
    accepted = _entry("Jenna", status="accepted")
    pending = _entry("Jen")
    entries = [accepted, pending]
    applied = await apply_reviews(
        _Session(entries),  # type: ignore[arg-type]
        entries=entries,
        reviews=[
            _review(accepted, "reject"),
            _review(pending, "merge", merge_into_id="not-an-id"),
        ],
        model="m",
    )
    assert applied == {}
    assert (accepted.status, pending.status) == ("accepted", "proposed")


async def test_terms_written_by_name_instead_of_id_are_found() -> None:
    accepted = _entry("Jenna", status="accepted")
    pending = _entry("Jen")
    entries = [accepted, pending]
    review = _review(pending, "merge", merge_into_id="Jenna")
    review.entry_id = "Jen"
    applied = await apply_reviews(
        _Session(entries),  # type: ignore[arg-type]
        entries=entries,
        reviews=[review],
        model="m",
    )
    assert applied == {str(pending.id): "merged"}
    assert pending.merged_into_id == accepted.id
