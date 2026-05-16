"""Schema for the iterative voice-extraction step.

Paired with ``../prompts/extract_voices_prompt.py``.

What changed in this revision
-----------------------------
The single ``voice_summary`` field is split into two fields:

- ``source_voice_observation`` — what the character is REALLY doing in
  the source language. Names specific linguistic markers grounded in
  THIS window's dialogue: particles, archaic vocabulary, register
  shifts, address conventions, deliberate non-standard spellings,
  deliberate non-standard grammar (a foreigner's broken cases, a
  child's syntax, dropped articles), signature speech patterns
  (verbal tics, stutters, fragmentation, repetitions), code-switching
  to other languages, and stable sociolect by class/era/profession —
  both lexicon AND cognitive/syntactic tendency. Every named feature
  must be tied to a specific phrase in the dialogue; do not project
  from role or profession (a teacher who speaks with a village accent
  has a village voice).

- ``target_voice_strategy`` — translation guidance, not a generation
  prompt. Read by the translator line by line. Each entry pairs a
  source trigger ("when you see X in this character's line…") with
  a move: mirror (carry directly), recast (substitute a
  target-language equivalent), or watch (a trap to avoid). Grammar
  errors, verbal tics, signature phrases, and code-switching usually
  mirror. Lexical register and source-specific particles usually
  recast. Eye-dialect is per-character: mirror with sparse equivalent
  eye-dialect for in-language regional/class accents (the Hardy/Eliot/
  Twain/Scott tradition), recast for foreign-speaker accents (use
  grammar errors, not stage-accent spellings). Stable sociolect
  splits: recast the lexicon, mirror the cognitive/syntactic tendency.

The two fields are different cognitive jobs:

1. *Observation* is reading work — look at the source, name what's
   happening linguistically.
2. *Strategy* is craft work — decide how the target language should
   render those features.

Conflating them into a single voice_summary forced the model to do
both at once, and produced vague results ("rural feel") that didn't
give the translator anything specific to work with. Splitting makes
each job nameable and reviewable independently — the author can edit
either field during voice review without disturbing the other.

Why generate both during extraction
-----------------------------------
The same model call sees the source dialogue and is best positioned to
write the observation. Writing the strategy in the same pass is cheap
(no extra API calls) and natural — observation and strategy inform
each other ("the character uses an emphatic particle → render with an
equivalent target-language marker"). Quality of model-produced
strategies is the weak link; that's why author review is critical.

The author's edit loop calibrates the strategies. If the model writes
"render in archaic-rural English" and the author refines to "render
in Hardy/Eliot country-servant register, specific markers: ye, afore,
reckon, no eye-dialect," that's the authorial intent translation
needs. Translation runs after review.

Other design choices (unchanged from previous revision)
-------------------------------------------------------
- Candidate pool capped at 8 per character.
- ID + name cross-check on every operation.
- IDs typed as ``str`` for Gemini schema compatibility.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


# ─── Closed enums ───────────────────────────────────────

VoiceNoteCategory = Literal[
    "pattern_to_watch",
    "consistency_concern",
    "unresolved_question",
]


# ─── Sub-models ─────────────────────────────────────────


class VoiceNote(BaseModel):
    """A working-memory note the model writes for its future self."""

    category: VoiceNoteCategory
    content: str = Field(description="One short note for the next pass.")


class CandidatePassage(BaseModel):
    """A representative passage for a character, drawn from this window.

    Candidates accumulate across the run. Selection happens later, by a
    different chain. The model's job here is to *contribute* — to flag
    moments worth keeping — not to pick a single best passage.
    """

    source_text: str = Field(
        description=(
            "3-5 consecutive sentences of this character's dialogue, "
            "verbatim from the source text. Verbatim — do not paraphrase."
        ),
    )
    why_representative: str = Field(
        description=(
            "One short clause: what does this passage show about this "
            "character's voice that's worth keeping? "
            "Examples: 'shows the diminutive shift toward Mira'; "
            "'rare moment of dropped facade'; "
            "'most representative of his commanding mode'. "
            "Selection later uses this reason when picking final passages."
        ),
    )


# ─── Delta operations ───────────────────────────────────


class NewVoiceProfile(BaseModel):
    """Create a voice profile for a character first speaking in this window.

    Includes BOTH voice fields (observation + strategy) AND seeds the
    candidate pool with one or more initial passages.
    """

    reasoning: str = Field(
        description=(
            "Brief grounding in the dialogue evidence — what about how "
            "this character speaks led to the observation and strategy "
            "below."
        ),
    )
    glossary_entry_id: str = Field(
        description="ID from the glossary character list. Copy verbatim.",
    )
    canonical_name: str = Field(
        description=(
            "Canonical name as it appears in the glossary character "
            "list. Cross-checked against ID; mismatched ops are dropped. "
            "Copy verbatim."
        ),
    )
    source_voice_observation: str = Field(
        description=(
            "What is this character REALLY doing in the source language? "
            "Name specific linguistic markers — particles, archaic "
            "vocabulary, eye-dialect spellings, non-standard grammar "
            "(case/gender/article/concord errors, foreign or child "
            "syntax), verbal tics and speech patterns (stutters, "
            "fragmentation, repetitions, signature phrases), "
            "code-switching to other languages and what the switching "
            "signals, stable sociolect by class/era/region/profession "
            "(lexicon AND syntactic/cognitive tendency — the scientist "
            "hedges, the peasant is concrete, the soldier terse), "
            "register shifts, address conventions. "
            "GROUNDING RULE: every named feature must be tied to a "
            "specific quoted or near-quoted phrase from THIS window's "
            "dialogue. Do not project features from role or profession "
            "(a teacher who speaks with a village accent has a village "
            "voice). If you cannot quote evidence, do not name the "
            "feature — write a notepad note instead. "
            "Specific is better than abstract: 'uses the -że emphatic "
            "particle (Łapaćże, lepiejże), archaic-rural lexicon "
            "(chłop, chałupa, dziad), deliberate misspellings as "
            "eye-dialect (tile, dzjewko)' beats 'rural and informal'. "
            "Written in the target language. 2-3 sentences."
        ),
    )
    target_voice_strategy: str = Field(
        description=(
            "Translation guidance for this character — NOT a generation "
            "prompt. Read by the translator line by line. Each entry "
            "pairs a source trigger ('when you see X in this character's "
            "line…') with a move: MIRROR (carry directly), RECAST "
            "(substitute a target-language equivalent), or WATCH (name "
            "a trap to avoid). Grammar errors, verbal tics, signature "
            "phrases, stutters, and code-switching usually mirror. "
            "Lexical register and source-specific particles usually "
            "recast. Eye-dialect is per-character: mirror with sparse "
            "equivalent eye-dialect for in-language regional/class "
            "accents (Hardy/Eliot/Twain/Scott are the tradition); "
            "recast for foreign-speaker accents (use grammar errors, "
            "not phonetic stage-accents). Stable sociolect splits: "
            "recast the lexicon, mirror the cognitive/syntactic tendency. "
            "Specific source-keyed rules beat abstract directives: "
            "'When his line uses the -że particle, render with would-ye "
            "or mind-ye. When his line has eye-dialect misspellings, "
            "MIRROR with sparse English eye-dialect (dropped -g, '\\'tis', "
            "'arf') plus register vocabulary (wench, reckon, afore). "
            "Watch for: y'all/ain\\'t (too American), dense phonetic "
            "transcription' beats 'render in archaic-rural English'. "
            "Written in the target language. 2-3 sentences. "
            "Author may refine during review — your job is a strong "
            "starting point, not a final answer."
        ),
    )
    initial_candidates: list[CandidatePassage] = Field(
        default_factory=list,
        description=(
            "One or more starting candidate passages from this window. "
            "Most profiles start with one; complex characters with "
            "multiple distinct voice displays may start with 2-3. "
            "The pool grows on later passes via AddCandidate."
        ),
    )


class ExtendVoiceProfile(BaseModel):
    """Replace observation and/or strategy with versions integrating new evidence.

    Either field can be updated independently — this window may sharpen
    the observation while leaving the strategy intact, or vice versa.
    Provide only the field(s) actually changing; ``None`` means
    "no change."

    Most passes will not extend. Only when this window meaningfully
    sharpens or contradicts what's recorded.
    """

    profile_id: str = Field(description="ID from the current voice profiles list. Copy verbatim.")
    canonical_name: str = Field(
        description=(
            "Canonical name from the current voice profiles list. "
            "Cross-checked against profile_id; mismatched ops are dropped."
        ),
    )
    new_source_voice_observation: str | None = Field(
        default=None,
        description=(
            "Updated observation, if this window's evidence justifies "
            "an update. Null if observation is unchanged. Same "
            "constraints as new-profile observation."
        ),
    )
    new_target_voice_strategy: str | None = Field(
        default=None,
        description=(
            "Updated strategy, if this window's evidence justifies an "
            "update. Null if strategy is unchanged. Same constraints "
            "as new-profile strategy. Note: most updates will be to "
            "observation; strategy changes less often, since it's a "
            "literary craft decision that doesn't shift with each new "
            "scene."
        ),
    )
    reasoning: str = Field(
        description=(
            "What new evidence in this window justifies the update(s). "
            "If you cannot point to specific new evidence, do not "
            "extend — leave the existing fields alone."
        ),
    )


class AddCandidate(BaseModel):
    """Add a candidate passage to an existing profile's pool.

    Use when this window contains a moment worth keeping for selection
    later, AND the pool has fewer than 8 entries, AND the passage shows
    something the existing candidates don't.
    """

    profile_id: str
    canonical_name: str = Field(
        description=(
            "Canonical name from the current voice profiles list. "
            "Cross-checked against profile_id; mismatched ops are dropped."
        ),
    )
    candidate: CandidatePassage
    reasoning: str = Field(
        description=(
            "Why this passage is worth keeping in the pool. What does "
            "it show that the existing candidates don't? Be specific."
        ),
    )


class ReplaceCandidate(BaseModel):
    """Swap a less-representative candidate for a better one.

    Use when the candidate pool is full (8 entries) and this window has
    a passage that's clearly more valuable than one of the existing
    candidates. Identify the candidate to remove by its
    ``why_representative`` text — exact match required.
    """

    profile_id: str
    canonical_name: str = Field(
        description=(
            "Canonical name from the current voice profiles list. "
            "Cross-checked against profile_id; mismatched ops are dropped."
        ),
    )
    remove_candidate_reason: str = Field(
        description=(
            "The ``why_representative`` text of the candidate to remove. "
            "Must match an existing candidate exactly."
        ),
    )
    new_candidate: CandidatePassage
    reasoning: str = Field(
        description=(
            "Why the new candidate is meaningfully better than the one "
            "being removed. Cosmetic improvement is not enough."
        ),
    )


# ─── The output ─────────────────────────────────────────


class VoiceUpdate(BaseModel):
    """The full delta produced by one voice-extraction pass."""

    window_summary: str = Field(
        description=(
            "One short paragraph orienting on the window. Not persisted."
        ),
    )
    new_profiles: list[NewVoiceProfile] = Field(default_factory=list)
    extensions: list[ExtendVoiceProfile] = Field(default_factory=list)
    candidate_additions: list[AddCandidate] = Field(default_factory=list)
    candidate_replacements: list[ReplaceCandidate] = Field(default_factory=list)
    notepad: list[VoiceNote] = Field(
        default_factory=list,
        description="Working memory carried into the next pass. At most one entry.",
    )

    @model_validator(mode="after")
    def _cap_notepad(self) -> Self:
        if len(self.notepad) <= 1:
            return self
        return self.model_copy(update={"notepad": self.notepad[:1]})


# ─── Prompt-input shapes ────────────────────────────────


class CharacterVoiceCompact(BaseModel):
    """Lean shape passed INTO the prompt to represent existing profiles.

    Includes BOTH voice fields plus the candidate pool size and the
    ``why_representative`` reasons of existing candidates. Token cost
    is higher than the previous single-summary form, but the model
    needs both fields to:

    - Decide whether new evidence in this window justifies extending
      observation, strategy, or both.
    - Avoid duplicating an observation that's already captured.

    Excludes the candidate passage source texts themselves (too long
    for prompt context).
    """

    id: str
    glossary_entry_id: str
    canonical_name: str
    source_voice_observation: str
    target_voice_strategy: str
    candidate_count: int = Field(
        description="Current size of the candidate pool. Cap is 8.",
    )
    candidate_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "The ``why_representative`` reasons of the existing "
            "candidates, in the order they were added. Used by the "
            "model to judge whether a new candidate would duplicate "
            "what's already there."
        ),
    )
    last_observed_window: int = Field(
        description="Window number where this profile last received an op.",
    )


class GlossaryCharacterRef(BaseModel):
    """Character entries from the glossary — sent for ALL character
    glossary entries (status != rejected)."""

    glossary_entry_id: str
    canonical_name: str
    variants: list[str] = Field(default_factory=list)
    has_voice_profile: bool = Field(
        description=(
            "Whether a voice profile already exists. False = create. "
            "True = extend, add candidates, or do nothing."
        ),
    )
