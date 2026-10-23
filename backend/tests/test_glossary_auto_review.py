"""Tests for carrying glossary decisions over to pending forms of a term."""

from uuid import uuid4

from app.services.glossary_auto_review import (
    PendingTerm,
    ReviewedTerm,
    plan_auto_decisions,
    term_forms,
)
from app.services.term_matching import is_same_term


def _reviewed(canonical: str, status: str, *, same_book: bool = True, variants=None):  # type: ignore[no-untyped-def]
    return ReviewedTerm(
        id=uuid4(),
        canonical_form=canonical,
        variants=variants or [],
        status=status,
        translation_recommendation={"suggestion": "translate", "proposed_target": canonical},
        same_book=same_book,
        book_title="Zaplataczka",
    )


def _pending(canonical: str, variants=None) -> PendingTerm:  # type: ignore[no-untyped-def]
    return PendingTerm(id=uuid4(), canonical_form=canonical, variants=variants or [])


def test_same_term_allows_endings_but_not_other_words() -> None:
    assert is_same_term("Strategii Obronnych", "Strategie Obronne")
    assert is_same_term("Wysoki Ród", "Wysokie Rody")
    assert is_same_term("Dwupaskowcy", "Dwupaskowy")
    assert is_same_term("pył", "Pył")
    assert not is_same_term("Sysjusz", "system")
    assert not is_same_term("Cień", "cieplak")
    assert not is_same_term("Pył", "Pyłomór")
    assert not is_same_term("Dzienniki", "Dzienniki Sysjusza")


def test_aliases_in_variants_are_not_forms() -> None:
    assert term_forms("Jen", ["Jen", "prosem", "prosiątkiem"]) == ["Jen"]


def test_form_of_a_term_removed_in_this_book_is_removed() -> None:
    source = _reviewed("Strategie Obronne", "rejected")
    pending = _pending("Strategii Obronnych")
    [d] = plan_auto_decisions([pending], [source])
    assert (d.entry_id, d.action, d.source) == (pending.id, "reject", source)
    assert d.reason == "Form of “Strategie Obronne”, which you removed."


def test_form_of_a_term_accepted_in_this_book_is_merged() -> None:
    [d] = plan_auto_decisions([_pending("Wysoki Ród")], [_reviewed("Wysokie Rody", "accepted")])
    assert d.action == "merge"


def test_term_accepted_in_another_book_is_accepted() -> None:
    other = _reviewed("Teoria Sita", "adjusted", same_book=False)
    [d] = plan_auto_decisions([_pending("Teoria Sita")], [other])
    assert d.action == "accept"
    assert d.reason == "You accepted this term in “Zaplataczka”."


def test_this_books_decision_wins_over_another_book() -> None:
    here = _reviewed("Pierwszy", "rejected")
    other = _reviewed("Pierwszy", "accepted", same_book=False)
    [d] = plan_auto_decisions([_pending("Pierwszego")], [other, here])
    assert d.source is here


def test_matches_with_two_terms_or_two_decisions_stay_pending() -> None:
    two_terms = [_reviewed("Zaplatacze", "accepted"), _reviewed("Zaplatacz", "accepted")]
    assert plan_auto_decisions([_pending("Zaplatacza")], two_terms) == []
    two_decisions = [
        _reviewed("Generał", "accepted", same_book=False),
        _reviewed("Generał", "rejected", same_book=False),
    ]
    assert plan_auto_decisions([_pending("Generał")], two_decisions) == []


def test_same_term_in_several_other_books_counts_once() -> None:
    books = [_reviewed("Fulgor", "accepted", same_book=False) for _ in range(3)]
    [d] = plan_auto_decisions([_pending("Fulgor")], books)
    assert d.action == "accept"


def test_unrelated_pending_term_is_left_alone() -> None:
    assert plan_auto_decisions([_pending("bylica")], [_reviewed("Fulgor", "accepted")]) == []
