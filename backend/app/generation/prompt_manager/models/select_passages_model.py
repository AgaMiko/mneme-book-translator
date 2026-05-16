"""Schema for the per-character passage selection step.

Paired with ``../prompts/select_passages_prompt.py``.

This is the SECOND chain in the voice pipeline. It runs after voice
extraction completes — once per character with at least one candidate
passage — and picks N final passages from that character's candidate
pool, where N is determined code-side from the character's glossary
occurrence_count percentile within this book.

The chain does NOT translate. Translation is the third chain. Selection's
only job is choosing which candidates become the canonical reference
passages.

Why a separate chain
--------------------
Selection wants to see the entire candidate pool at once and reason
across them ("which 3 of these 8 candidates show the most distinct
voice displays?"). This is a different cognitive task than
window-by-window extraction, and it benefits from a focused prompt
and a single deliberate decision.

Why not done by code
--------------------
The percentile math (which decides *how many* passages each character
gets) IS done by code — it's deterministic and shouldn't burn API
calls. But the selection itself ("which 3 of these 8?") requires
reading the passage texts and reasoning about voice display
differences. That's model work.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SelectedPassage(BaseModel):
    """One of the final selected passages for a character."""

    candidate_source_text: str = Field(
        description=(
            "The exact source_text of the candidate being selected. "
            "Must match one of the candidates in the input pool verbatim — "
            "the system looks up the candidate by this text. If the "
            "lookup fails, the selection is dropped."
        ),
    )
    why_this_one: str = Field(
        description=(
            "Why this passage made the final cut. Should reference what "
            "voice display it shows that other selections don't. "
            "Examples: 'his commanding mode in its purest form'; "
            "'the rare tender register with Mira, otherwise unrepresented'; "
            "'the moment of dropped facade when Stein confronts Agata'."
        ),
    )


class PassageSelection(BaseModel):
    """The selection output for one character's pool."""

    profile_id: str = Field(
        description=(
            "ID of the voice profile being selected for. Same string as "
            "in the input."
        ),
    )
    canonical_name: str = Field(
        description=(
            "Canonical name of the character. The system cross-checks "
            "against profile_id; mismatched selections are dropped."
        ),
    )
    reasoning: str = Field(
        description=(
            "Brief overall rationale: how did you approach selection "
            "for this character? Two or three clauses, not a paragraph. "
            "Reference the voice observation and strategy and what the selected passages "
            "collectively cover."
        ),
    )
    selected_passages: list[SelectedPassage] = Field(
        description=(
            "The chosen passages in order of priority — most "
            "representative first. Length must equal the requested "
            "passage_count from the input. If the candidate pool has "
            "fewer entries than passage_count, return all candidates."
        ),
    )


class CandidateInPool(BaseModel):
    """One candidate as presented to the selection chain.

    Has both the source text and the original ``why_representative``
    reasoning the extraction model wrote when adding it to the pool.
    Selection uses both to decide whether to include this candidate
    in the final set.
    """

    source_text: str
    why_representative: str
    first_seen_window: int = Field(
        description="Window where this candidate was first added.",
    )
