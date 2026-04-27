"""Schema for the iterative voice-extraction step.

Paired with ``../prompts/extract_voices_prompt.py``.

Design
------
Voice extraction runs after glossary extraction is complete. Each pass
sees one window of text plus the running voice profiles, and returns a
*delta* — the model reasons about *changes*, not state.

What a voice profile is
-----------------------
Two fields, both serving translation directly:

1. ``voice_summary`` — 2-3 sentences of prose describing how the
   character speaks: register, diction, address strategy, situational
   shifts. Read as a *constraint* on translation, not as content.
   Single field, no separate register / diction / verbal_tics breakdown.
   Verbal tics specifically are NOT collected: a translator given a
   list of phrases will reuse them where the source doesn't, amplifying
   the recurrence pattern beyond the original. Source text carries
   vocabulary; the profile carries voice constraints.

2. ``reference_passage`` — 3-4 sentences of real dialogue from the
   manuscript, plus the model's translation of those exact sentences.
   This is the calibration sample. Translation downstream uses this
   pair (Polish ↔ English) as a known-good example of how the character
   should sound in translation, with the author's edits as ground
   truth.

The author reviews each profile by reading the summary and the
reference translation and accepting / editing / rejecting. Their
edits become the canonical version translation will use.

Iteration model
---------------
Per window, the model can:

- **Create** a new profile when a character speaks for the first time,
  including its voice_summary and an initial reference passage drawn
  from this window.
- **Extend** an existing profile by replacing the voice_summary with
  one that integrates new evidence (full replacement, not patch).
- **Replace the reference passage** when this window contains a
  meaningfully better representative passage than the stored one.
  Separate explicit operation requiring reasoning — prevents the
  model from churning the reference cosmetically each window.

What the model does NOT do
--------------------------
- It does not output dialogue counts or excerpts for analytics.
  ``voice_service`` derives those deterministically from the source.
- It does not collect verbal tics. (See above; behavioral risk.)
- It does not categorize register / speech-acts / context shifts.
  All of that is folded into the prose voice_summary.

Layering
--------
- Glossary entries are the canonical character list. Voice profiles
  link via ``glossary_entry_id`` and never invent characters of their
  own.
- The persisted ORM shape (``app.models.voice.CharacterVoice``) is a
  third, distinct shape. Service code converts.

ID typing — ``str``, not ``UUID``
---------------------------------
From the model's perspective, every ID it sees is an opaque token to
copy back. Typing those fields as ``UUID`` adds ``format: "uuid"`` to
the JSON Schema sent to Gemini and makes Pydantic strict-validate the
format on parse — one stray character and the whole window crashes.
The glossary chain has the same shape and uses ``str`` everywhere;
voice follows the same pattern. Service code converts at the DB
boundary.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

# Do not use ``Field(max_length=…)`` or ``StringConstraints`` here.
# Gemini's response-schema path does not support those JSON Schema
# keywords; they either break generation or are ignored. Length
# discipline lives in field descriptions plus the prompt template.


# ─── Closed enum ────────────────────────────────────────

VoiceNoteCategory = Literal[
    "pattern_to_watch",       # something noticed but not yet codified
    "consistency_concern",    # a character's voice may have drifted across windows
    "unresolved_question",    # something the author should weigh in on
]


# ─── Sub-models ─────────────────────────────────────────


class VoiceNote(BaseModel):
    """A working-memory note the model writes for its future self."""

    category: VoiceNoteCategory
    content: str = Field(
        description="One short note for the next pass.",
    )


# ─── Delta operations ───────────────────────────────────


class NewVoiceProfile(BaseModel):
    """Create a voice profile for a character first speaking in this window.

    Reasoning is first because both the voice_summary and the choice of
    reference passage benefit from the model committing to its analysis
    before producing the artifacts.

    The ``glossary_entry_id`` MUST point to a character entry from the
    glossary list provided in the prompt. The model never invents IDs;
    if a speaker appears who isn't in the glossary, the model writes a
    note in the notepad and skips creating a profile.
    """

    reasoning: str = Field(
        description=(
            "Brief grounding in the dialogue evidence — what about the way "
            "this character speaks led to the voice_summary below, and why "
            "the chosen passage represents the voice well. One or two "
            "clauses, not a scene recap."
        ),
    )
    glossary_entry_id: str = Field(
        description=(
            "ID of the character's glossary entry — the same "
            "`glossary_entry_id` string as in the character list provided "
            "in the prompt."
        ),
    )
    voice_summary: str = Field(
        description=(
            "2-3 sentences describing how this character speaks. Covers "
            "register, diction, address strategy, and any situational "
            "shifts — all in flowing prose, not separate slots. Reads as "
            "a CONSTRAINT for the translator, not as content to copy. "
            "Good: 'Speaks in clipped urgent military commands, softening "
            "to a conspiratorial tone when discussing illness. Uses "
            "diminutives toward Mira in moments of intimacy or "
            "condescension. Sounds like a soldier maintaining a facade of "
            "control while delivering bad news.' "
            "Bad: 'Speaks in clipped commands like Spokojnie spokojnie!' "
            "(That tells the translator what to write; the translator will "
            "write it whether the source contains it or not.)"
        ),
    )
    reference_passage_source: str = Field(
        description=(
            "3-4 consecutive sentences of this character's dialogue, "
            "verbatim from this window's source text. The passage should "
            "show voice fully, be self-contained, and be representative "
            "(not extreme). Include voice-distinguishing features the "
            "translator must preserve. Verbatim — do not paraphrase or "
            "edit the source."
        ),
    )
    reference_passage_translation: str = Field(
        description=(
            "Your translation of those exact sentences into the target "
            "language. Preserve the voice characteristics in voice_summary. "
            "Do not insert phrases not present in the source. Aim for what "
            "a careful human literary translator would produce — this "
            "translation will be reviewed by the author and used as a "
            "calibration sample for the rest of translation."
        ),
    )


class ExtendVoiceProfile(BaseModel):
    """Replace voice_summary with one that integrates new evidence.

    Full replacement, not patch — the model writes a fresh summary that
    incorporates whatever new observation this window provides. Most
    passes will not extend; only when this window meaningfully sharpens
    or contradicts the prior summary.

    Does NOT touch the reference passage. For that, use
    ``ReplaceReferencePassage``.
    """

    profile_id: str = Field(
        description=(
            "ID of the existing profile — the same `id` string as in the "
            "current voice-profile table."
        ),
    )
    new_voice_summary: str = Field(
        description=(
            "Updated voice_summary integrating new evidence from this "
            "window. Same constraints as the new-profile voice_summary: "
            "2-3 sentences of prose, describes voice as a constraint, no "
            "phrase examples to copy."
        ),
    )
    reasoning: str = Field(
        description=(
            "What new evidence in this window justifies updating the "
            "summary. If you cannot point to specific new evidence, do "
            "not extend — leave the existing summary alone."
        ),
    )


class ReplaceReferencePassage(BaseModel):
    """Replace the stored reference passage with a better one from this window.

    Use sparingly. Only when this window contains a passage that
    *meaningfully* shows voice better than the stored one — for example,
    the stored passage was a single short line and this window has a
    fuller exchange that shows register and address strategy together.

    Cosmetic improvement is not sufficient justification. If the stored
    passage is adequate, leave it alone.
    """

    profile_id: str
    new_reference_passage_source: str = Field(
        description=(
            "Replacement passage, verbatim from this window. Same "
            "selection criteria as new-profile passages: 3-4 sentences, "
            "voice-rich, self-contained, representative."
        ),
    )
    new_reference_passage_translation: str = Field(
        description=(
            "Fresh translation of the replacement passage. Same quality "
            "expectations as new-profile translations."
        ),
    )
    reasoning: str = Field(
        description=(
            "Why this passage is meaningfully better than the stored one. "
            "Be specific — 'shows the diminutive shift the prior passage "
            "missed' is good; 'better passage' is not."
        ),
    )


# ─── The output ─────────────────────────────────────────


class VoiceUpdate(BaseModel):
    """The full delta produced by one voice-extraction pass.

    Field order follows the schema-first principle: orient on the window
    first, then commit operations, then curate working memory for next
    pass.
    """

    window_summary: str = Field(
        description=(
            "One short paragraph: who speaks in this window, dialogue "
            "density, register shifts worth noting — orients you before "
            "operations. Keep it compact; the pipeline does not persist "
            "this field."
        ),
    )
    new_profiles: list[NewVoiceProfile] = Field(default_factory=list)
    extensions: list[ExtendVoiceProfile] = Field(default_factory=list)
    reference_replacements: list[ReplaceReferencePassage] = Field(default_factory=list)
    notepad: list[VoiceNote] = Field(
        default_factory=list,
        description=(
            "Working memory carried into the next pass. At most one "
            "entry. Use it for things you've noticed but haven't yet "
            "codified — speakers not in the glossary, possible voice "
            "drift across windows, patterns to confirm later."
        ),
    )

    @model_validator(mode="after")
    def _cap_notepad(self) -> Self:
        if len(self.notepad) <= 1:
            return self
        return self.model_copy(update={"notepad": self.notepad[:1]})


# ─── Prompt-input shape ─────────────────────────────────


class CharacterVoiceCompact(BaseModel):
    """The lean shape passed INTO the prompt to represent existing profiles.

    Includes the full voice_summary because it's the only descriptive
    field — the model genuinely needs it to decide whether new dialogue
    is consistent with the stored voice. Includes the source half of
    the reference passage so the model can decide whether to issue a
    ReplaceReferencePassage operation; deliberately excludes the
    translation half — the model's job is selecting source passages,
    not reviewing its own prior translations.
    """

    id: str
    glossary_entry_id: str
    canonical_name: str
    voice_summary: str
    reference_passage_source: str
    last_observed_window: int = Field(
        description=(
            "Window number where this profile last received an operation. "
            "Helps the model spot characters whose voice may have drifted "
            "because they haven't been observed for many windows."
        ),
    )


class GlossaryCharacterRef(BaseModel):
    """Character entries from the glossary, passed in so the model knows
    who can be the subject of a voice operation.

    Sent for ALL character glossary entries (status != rejected),
    including ones that don't yet have a voice profile. The model uses
    these to attach new profiles via ``glossary_entry_id``.
    """

    glossary_entry_id: str
    canonical_name: str
    variants: list[str] = Field(default_factory=list)
    has_voice_profile: bool = Field(
        description=(
            "Whether a voice profile already exists. False = creating a "
            "profile is the right operation; True = extend or replace "
            "reference (or do nothing if the existing profile fits this "
            "window's evidence)."
        ),
    )
