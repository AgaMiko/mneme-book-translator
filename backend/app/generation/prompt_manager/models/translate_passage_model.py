"""Schema for the per-passage translation step.

Paired with ``../prompts/translate_passage_prompt.py``.

This is the THIRD chain in the voice pipeline. It runs once per
selected passage, after passage selection completes. It takes:

- The source passage (verbatim)
- The character's source_voice_observation and target_voice_strategy
- The full set of accepted glossary terms
- Source and target languages

And produces a literary translation of the passage that respects the
voice constraint AND the accepted glossary terminology.

Why per-passage, not per-character
-----------------------------------
Each selected passage is independent — its translation depends on the
voice and glossary, not on other passages' translations. Per-passage
calls are smaller (one passage at a time, not all of a character's),
isolate failures (one bad call doesn't lose a character's work), and
let translation parallelize cleanly if needed later.

About 50-80 calls per book at this granularity. With a more capable
model, the cost is real but bounded. With Flash Lite it's negligible.

Glossary terms in the prompt
----------------------------
The chain receives the FULL accepted glossary, not just terms that
appear in the passage. Reasons:
- Service code can't reliably detect which terms appear (variants,
  inflections, partial matches).
- Terms not in the passage cost only prompt tokens; they don't change
  the output.
- The full list reinforces the system's commitment to consistent
  terminology — the model sees how many decisions have been made.

This is the chain where glossary discipline is enforced. The previous
voice extraction chain ignored the glossary entirely — that's why
translations came out inconsistent (Pył in one, Dust in another).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TranslationStrategy = Literal[
    "keep_original",
    "translate_literally",
    "adapt",
    "transliterate",
]


class GlossaryTermRef(BaseModel):
    """One accepted glossary term, as passed into the translation prompt.

    The strategy field tells the model not just *what* the target form
    is, but *why* — which lets the model handle related terms it might
    encounter (e.g., a new place name should follow the same strategy
    as established place names in this book).
    """

    term_source: str
    term_target: str
    translation_strategy: TranslationStrategy
    notes: str | None = Field(
        default=None,
        description=(
            "Optional notes the author added during glossary review. "
            "Often null. When present, may explain context or "
            "translator-relevant nuance."
        ),
    )


class PassageTranslation(BaseModel):
    """The translation of one selected passage."""

    selected_passage_id: str = Field(
        description=(
            "Opaque ID of the passage being translated. The same string "
            "as in the input — copy verbatim. Used by service code to "
            "match the translation back to the right database row."
        ),
    )
    canonical_name: str = Field(
        description=(
            "Canonical name of the speaking character. Cross-checked by "
            "the service layer against the passage's profile."
        ),
    )
    translation: str = Field(
        description=(
            "The translated passage. Should follow target_voice_strategy, "
            "use source_voice_observation as context, respect every "
            "glossary term that appears in the source, and read as if "
            "originally written in the target language."
        ),
    )
    reasoning: str = Field(
        description=(
            "One or two clauses on translation choices that affect "
            "voice or required interpretation. Examples: 'kept the "
            "diminutive as <target equivalent>'; 'translated the "
            "register shift in sentence 2 by switching to short "
            "imperatives'. Brief; this is for review traceability, not "
            "a justification essay."
        ),
    )
