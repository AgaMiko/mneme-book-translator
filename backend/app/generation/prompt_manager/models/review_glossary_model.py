"""Schema for the glossary review step: decide pending terms like the author would.

Paired with ``../prompts/review_glossary_prompt.py``.

After extraction, and after pending forms of reviewed terms were decided
without the LLM (``app.services.glossary_auto_review``), the remaining
pending terms go to one review call per batch. The model sees the pending
terms with passages from the book, the terms already accepted, and the
author's past removals, and returns one decision per pending term.

The author checks these decisions later; each one carries a confidence so
the uncertain ones can be checked first.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReviewDecision = Literal["accept", "reject", "merge"]


class TermReview(BaseModel):
    """The decision for one pending term."""

    entry_id: str = Field(description="The pending term's id, copied exactly from its table row.")
    reasoning: str = Field(
        description=(
            "One plain sentence the author will read next to the decision: why. "
            "Point to the passages or to a similar past decision."
        ),
    )
    decision: ReviewDecision = Field(
        description=(
            "accept: keep it in the glossary. reject: it needs no glossary entry. "
            "merge: it is the same person, place or thing as another term."
        ),
    )
    merge_into_id: str | None = Field(
        default=None,
        description=(
            "Only for merge: the id of the term it is the same as, from the accepted "
            "terms or the pending terms. Otherwise null."
        ),
    )
    confidence: Literal["high", "low"] = Field(
        description=(
            "low whenever a careful reader could decide the other way: the passages "
            "do not settle it, or the author's past decisions on similar terms point "
            "both ways."
        ),
    )
    wrong_variants: list[str] = Field(
        default_factory=list,
        description=(
            "Variants listed for this term that are not a form or a name of it, "
            "for example another character's nickname or an unrelated word. "
            "Copy them exactly. Empty when all variants are right."
        ),
    )
    better_target: str | None = Field(
        default=None,
        description=(
            "Only when the proposed English is clearly wrong, for example a plant "
            "kept in the source language when it has a common English name: the "
            "English you would use. Otherwise null."
        ),
    )


class GlossaryReview(BaseModel):
    reviews: list[TermReview] = Field(
        description="Exactly one review per pending term in the table, in any order.",
    )
