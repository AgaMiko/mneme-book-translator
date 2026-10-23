"""Carry the author's glossary decisions over to pending forms of the same term.

Extraction often proposes a term the author has already decided on, in
another grammatical form ("Strategii Obronnych" after "Strategie Obronne"
was removed) or in another book of the same series. Those pending terms get
the same decision without asking:

- a form of a term accepted in this book is merged into it;
- a form of a term removed in this book, or in another book, is removed;
- a form of a term accepted in another book is accepted with that book's
  English translation.

Only the author's own decisions count as evidence, never earlier automatic
ones. A pending term that matches two different reviewed terms, or the same
term with different decisions, stays pending. Every automatic decision is
recorded on the row (``GlossaryEntry.auto_review``) so the author can
confirm or undo it later.

Pure planning lives here; ``glossary_service.apply_form_matches`` loads the
rows and applies the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from app.services.term_matching import fold, is_form_of, is_same_term

if TYPE_CHECKING:
    from uuid import UUID

ACCEPTED_STATUSES = ("accepted", "adjusted")

AutoAction = Literal["merge", "accept", "reject"]


@dataclass(frozen=True, slots=True)
class ReviewedTerm:
    """A term the author accepted or removed, in this book or another one."""

    id: UUID
    canonical_form: str
    variants: list[str]
    status: str
    translation_recommendation: dict[str, Any]
    same_book: bool
    book_title: str = ""


@dataclass(frozen=True, slots=True)
class PendingTerm:
    id: UUID
    canonical_form: str
    variants: list[str]


@dataclass(frozen=True, slots=True)
class AutoDecision:
    entry_id: UUID
    canonical_form: str
    action: AutoAction
    source: ReviewedTerm

    @property
    def reason(self) -> str:
        verb = "accepted" if self.source.status in ACCEPTED_STATUSES else "removed"
        where = "" if self.source.same_book else f" in “{self.source.book_title}”"
        if fold(self.canonical_form) == fold(self.source.canonical_form):
            return f"You {verb} this term{where}."
        return f"Form of “{self.source.canonical_form}”, which you {verb}{where}."


def term_forms(canonical_form: str, variants: list[str]) -> list[str]:
    """The canonical form plus the variants that are forms of it.

    Variants also hold aliases and nicknames ("prosiątkiem" under "Jen");
    those are not evidence that two rows are the same term.
    """
    return [canonical_form] + [v for v in variants if is_form_of(canonical_form, v)]


def _matches(a: list[str], b: list[str]) -> bool:
    return any(is_same_term(x, y) for x in a for y in b)


def plan_auto_decisions(
    pending: list[PendingTerm],
    reviewed: list[ReviewedTerm],
) -> list[AutoDecision]:
    """Decide each pending term that is a form of exactly one reviewed term.

    Decisions in this book win over other books. Among other books, several
    rows for the same term with the same decision count as one.
    """
    reviewed_forms = [(r, term_forms(r.canonical_form, r.variants)) for r in reviewed]
    out: list[AutoDecision] = []
    for p in pending:
        forms = term_forms(p.canonical_form, p.variants)
        hits = [r for r, rf in reviewed_forms if _matches(forms, rf)]
        same_book = [r for r in hits if r.same_book]
        candidates = same_book or hits
        if not candidates:
            continue
        accepted = {r.status in ACCEPTED_STATUSES for r in candidates}
        terms = {fold(r.canonical_form) for r in candidates}
        if len(accepted) > 1 or len(terms) > 1:
            continue
        source = candidates[0]
        if source.status not in ACCEPTED_STATUSES:
            action: AutoAction = "reject"
        elif source.same_book:
            action = "merge"
        else:
            action = "accept"
        out.append(
            AutoDecision(
                entry_id=p.id, canonical_form=p.canonical_form, action=action, source=source
            )
        )
    return out
