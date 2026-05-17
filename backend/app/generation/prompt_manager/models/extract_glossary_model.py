"""Schema for the iterative glossary extraction step.

Paired with ``../prompts/extract_glossary_prompt.py``.

Design
------
The glossary is built across many windowed passes (see
``app.constants.glossary_extraction`` for window size and overlap). Each pass
returns a *delta* against the existing glossary
rather than a full new glossary state — this is the schema-first equivalent
of "ask for decisions, not estimates": the model reasons about what's
changed, not about what already exists.

Four operation types cover everything a pass can do:

- ``new_entries``  — add a brand-new term to the glossary
- ``extensions``   — attach a newly-seen variant to an existing entry
- ``merges``       — collapse two existing entries (the model decided they're the same thing)
- ``refinements``  — sharpen meaning / type / translation on an existing entry

Plus a short ``notepad`` the model uses as private working memory across passes
(field description states what belongs there).

Two shapes for the same concept
-------------------------------
- ``GlossaryEntryCompact``  goes INTO the prompt as the current state.
                            Lean — just enough for the model to decide whether
                            something is a duplicate, extension, or new entry.
- The output operations     come OUT of the prompt as the delta.

The persisted ORM shape (``app.models.glossary.GlossaryEntry``) is a third,
distinct thing — service code converts between the LLM delta and the DB rows.
The LLM never sees workflow fields like ``status`` (proposed / accepted /
rejected) — those are FE/BE concerns.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ─── Closed enums ───────────────────────────────────────

TermType = Literal[
    "character_name",  # proper names of people (not creatures — those go to lore_term)
    "place_name",  # proper names of places (incl. descriptive toponyms)
    "organization",  # groups, factions, institutions
    "lore_term",  # in-world coined: magic, sci-fi tech, artifacts, named creatures,
    # named in-world events, in-world religious concepts (sound vs meaning)
    "cultural_term",  # real-world culture-specific (food, dress, customs readers may not share)
    "specialized_usage",  # common words with a dedicated in-world sense (often the hardest bucket)
    "other",  # escape hatch — use sparingly; reasoning must justify
]

TranslationSuggestion = Literal[
    "keep_original",
    "translate",
]


# ─── Sub-models ─────────────────────────────────────────


class TranslationRecommendation(BaseModel):
    """How this term should read in English running text."""

    suggestion: TranslationSuggestion
    proposed_target: str | None = Field(
        default=None,
        description=(
            "The concrete form for English running text: normally English words or "
            "romanization without Polish diacritics. For semantically transparent "
            "names, prefer a translated English name that preserves the image. Explain "
            "in rationale rather than omitting the field."
        ),
    )
    alternative_targets: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Optional further English renderings when several defensible options exist "
            "(calque vs paraphrase, formal vs colloquial title, two plausible "
            "romanizations). Best-first after proposed_target, which stays the default "
            "pick for automation. Leave empty when one reading is clearly best."
        ),
    )
    rationale: str = Field(
        description=(
            "Why this suggestion and proposed_target fit. One to three short "
            "sentences. For descriptive names (toponyms, orders built from common "
            "words), name the morpheme-level sense you carried into English. Mention "
            "when you dropped Polish diacritics in proposed_target for running English "
            "prose, or when you deliberately kept Polish (only with the keep_original "
            "suggestion). "
            "When alternative_targets is non-empty, briefly contrast the options. "
            "Also use for register (archaic, title, word family) or when the author "
            "might override your default."
        ),
    )

    @model_validator(mode="after")
    def _dedupe_alternatives_against_primary(self) -> TranslationRecommendation:
        primary = (self.proposed_target or "").strip()
        key_p = primary.lower()
        seen: set[str] = {key_p} if key_p else set()
        cleaned: list[str] = []
        for raw in self.alternative_targets:
            a = raw.strip()
            k = a.lower()
            if not k or k in seen:
                continue
            seen.add(k)
            cleaned.append(a)
            if len(cleaned) >= 5:
                break
        if cleaned == self.alternative_targets:
            return self
        return self.model_copy(update={"alternative_targets": cleaned})


# ─── Delta operations ───────────────────────────────────


class NewTerm(BaseModel):
    """Add a brand-new term to the glossary.

    Reasoning is first because the decision (the type and recommendation)
    benefits from the model committing to its analysis before classifying.
    """

    reasoning: str = Field(
        description=(
            "Why this is a glossary-worthy term and how ``term_type`` and the "
            "translation recommendation follow from the text. Always include at least "
            "one short clause on whether the surface form is semantically transparent "
            "for an English reader versus opaque, and whether you are translating for "
            "meaning or romanizing (guides ``keep_original`` vs ``translate``). "
            "When ``term_type`` is ``other``, state clearly why no other bucket fits — "
            "use ``other`` sparingly."
        ),
    )
    canonical_form: str = Field(
        description=(
            "The form the term is most often referred to by (not necessarily the "
            "first occurrence). For names, the bare name without articles. Preserve "
            "Polish spelling and diacritics here even when proposed_target is "
            "romanized or translated for English prose."
        ),
    )
    variants: list[str] = Field(
        default_factory=list,
        description=(
            "Other surface forms seen in this window (diminutives, "
            "alternate spellings, descriptive epithets that point to this entry)."
        ),
    )
    term_type: TermType = Field(
        description=(
            "One bucket per translation *decision shape*. ``character_name``: proper "
            "names of people (transliterate vs keep original; literal translation rare). "
            "``place_name``: proper names of places (descriptive toponyms may warrant "
            "image-preserving English). ``organization``: factions, institutions, "
            "groups (often keep a proper-noun spine, translate descriptive pieces). "
            "``lore_term``: source-coined in-world vocabulary — magic, sci-fi tech, "
            "artifacts, named creatures, named in-world events, in-world religion — "
            "core question whether sound is load-bearing or only meaning. "
            "``cultural_term``: real-world culture-specific items (e.g. food, dress) "
            "where the question is reader recognition vs gloss — not for fictional "
            "coinings. ``specialized_usage``: ordinary-looking words with a loaded "
            "in-world sense. ``other``: only when nothing else fits; use rarely and "
            "say why in ``reasoning``."
        ),
    )
    meaning: str = Field(
        description=(
            "What this term refers to, in clear English for someone who does not "
            "know Polish. One to three sentences. When the term belongs to a "
            "derivational or conceptual family already in the glossary (same root, "
            "verb and agent noun, shared in-world metaphor), name the relatives and "
            "the English pattern you are using so translations stay consistent."
        ),
    )
    translation_recommendation: TranslationRecommendation


class ExtendOperation(BaseModel):
    """Attach newly-seen variants to an existing glossary entry.

    Use when this window introduced a new surface form (diminutive,
    epithet, alternate spelling) for a term that's already in the glossary.

    ``reasoning`` is first so the model commits to the justification before
    the concrete ``entry_id`` and ``new_variants`` (same ordering pattern as
    ``NewTerm``, ``MergeOperation``, ``RefineOperation``).
    """

    reasoning: str = Field(
        description="Brief justification — typically why these forms refer to the same entity.",
    )
    entry_id: str = Field(
        description=(
            "ID of the existing entry to extend — the same `id` string as in the "
            "current glossary table."
        ),
    )
    new_variants: list[str] = Field(
        min_length=1,
        description="Variants seen in this window that aren't already on the entry.",
    )


class MergeOperation(BaseModel):
    """Collapse two existing entries the model now believes are the same thing.

    The loser's variants are appended to the winner's variants. The
    winner's other fields are kept; if a refinement is also needed,
    issue a separate ``RefineOperation`` against the winner.
    """

    reasoning: str = Field(
        description=(
            "Why these entries refer to the same entity and why the "
            "winner is the more canonical form."
        ),
    )
    winner_id: str = Field(
        description="The entry to keep (glossary `id` string from the current state).",
    )
    loser_id: str = Field(
        description="The entry to remove (its variants migrate to the winner).",
    )


class RefineOperation(BaseModel):
    """Update fields on an existing entry as understanding improves.

    Only include fields that should change. Untouched fields keep their
    current values on the persisted entry. Use sparingly — most passes
    should only add or extend, not refine.
    """

    reasoning: str = Field(
        description="What new evidence in this window justifies the change.",
    )
    entry_id: str = Field(
        description="ID of the entry to refine (same `id` as in the current glossary table).",
    )
    new_canonical_form: str | None = Field(default=None)
    new_term_type: TermType | None = None
    new_meaning: str | None = Field(default=None)
    new_translation_recommendation: TranslationRecommendation | None = None


# ─── The output ─────────────────────────────────────────


class GlossaryUpdate(BaseModel):
    """The full delta produced by one extraction pass.

    Field order follows the schema-first principle: the model thinks
    about the window before deciding what to change, then commits the
    operations, then curates its working memory for the next pass.
    """

    window_summary: str = Field(
        description=(
            "One short paragraph naming what this window of text is about, "
            "before listing operations. Helps the model orient before deciding."
        ),
    )
    new_entries: list[NewTerm] = Field(default_factory=list)
    extensions: list[ExtendOperation] = Field(default_factory=list)
    merges: list[MergeOperation] = Field(default_factory=list)
    refinements: list[RefineOperation] = Field(default_factory=list)
    notepad: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Private scratch for the next pass only (at most three short strings): "
            "concrete reminders such as spellings to watch or threads to reconcile — "
            "not a copy of the glossary, not progress bookkeeping, not editorial "
            "commentary on the novel. Omit when nothing should survive."
        ),
    )


# ─── Prompt-input shape ─────────────────────────────────


class GlossaryEntryCompact(BaseModel):
    """The lean shape passed INTO the prompt to represent existing entries.

    Includes ``variants`` because without them the model can't distinguish
    "this is a new term" from "this is a known term under a new surface form."
    Excludes ``rationale`` and full ``meaning`` reasoning — those bloat the
    prompt without changing extraction decisions on the current window.
    """

    id: str
    canonical_form: str
    variants: list[str] = Field(default_factory=list)
    term_type: TermType
    meaning: str
    translation_suggestion: TranslationSuggestion
    alternative_targets: list[str] = Field(
        default_factory=list,
        description="Other English options already stored for this entry, if any.",
    )
