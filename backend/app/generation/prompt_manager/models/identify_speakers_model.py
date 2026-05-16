"""Schema for the speaker-identification step (Pass 1).

Paired with ``../prompts/identify_speakers_prompt.py``.

What this step does
-------------------
For each manuscript window, identify which glossary characters have at
least one quoted speaking line. Output is a list of (character,
quoted_evidence) edges plus a notepad for cross-window state.

Why a dedicated step
--------------------
Voice extraction (Pass 2) historically did two cognitive jobs at once:
*identify which glossary characters spoke in this window* AND *produce
a voice profile for each*. Splitting those jobs gives:

- A simpler, cheaper Pass 1 that the model is good at.
- A Pass 2 with a known, narrow candidate pool — tighter grounding,
  fewer identity-leak failure modes (the "Opus" leak).

Pass 1 is intentionally narrow. It does NOT profile voices, translate,
or discover new characters. The narrowness is the point.

Two non-negotiables (cross-checked on the way out)
--------------------------------------------------
1. Every speaker carries ``glossary_entry_id`` AND ``canonical_name``
   copied verbatim from the glossary character list. The validator
   resolves the ID against the glossary and drops entries whose
   ``canonical_name`` doesn't match — same pattern voice extraction
   uses.
2. Every speaker carries ``quoted_evidence``: a verbatim phrase from
   the speaker's quoted line in THIS window. The validator confirms
   the substring actually appears in the window text and drops
   entries whose evidence is hallucinated.

The two checks together make Pass 1's output meaningfully grounded:
no speaker can be claimed without a real quote anchoring the claim.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


# ─── Closed enums ───────────────────────────────────────

SpeakerNoteCategory = Literal[
    "unresolved_speaker",
    "ambiguous_attribution",
    "pattern_to_watch",
]


# ─── Sub-models ─────────────────────────────────────────


class SpeakerNote(BaseModel):
    """A working-memory note carried into the next pass."""

    category: SpeakerNoteCategory
    content: str = Field(description="One short note for the next pass.")


class SpeakerInWindow(BaseModel):
    """One glossary character identified as speaking in this window."""

    reasoning: str = Field(
        description=(
            "One short sentence: which line in this window is theirs "
            "and what attribution cue identifies them — speaking-verb "
            "tag (powiedział X), addressee, scene context, POV. "
            "Reasoning before the structured fields so the model "
            "anchors its decision in evidence first."
        ),
    )
    glossary_entry_id: str = Field(
        description="ID from the glossary character list. Copy verbatim.",
    )
    canonical_name: str = Field(
        description=(
            "Canonical name as it appears in the glossary character "
            "list. Cross-checked against ``glossary_entry_id``; "
            "mismatched entries are dropped. Copy verbatim."
        ),
    )
    quoted_evidence: str = Field(
        description=(
            "5-15 words copied verbatim from this character's quoted "
            "line in THIS window. The validator checks that the "
            "phrase actually appears in the window text; entries whose "
            "evidence is hallucinated are dropped. If you cannot cite "
            "a verbatim phrase, do not list this speaker — write a "
            "notepad entry (``ambiguous_attribution``) instead."
        ),
    )


# ─── The output ─────────────────────────────────────────


class SpeakersInWindow(BaseModel):
    """Pass 1's output for one window."""

    window_summary: str = Field(
        description=(
            "One short paragraph orienting on the window — who's "
            "present, what's happening. Not persisted; helps the "
            "model think before listing speakers."
        ),
    )
    speakers: list[SpeakerInWindow] = Field(default_factory=list)
    notepad: list[SpeakerNote] = Field(
        default_factory=list,
        description="Working memory carried into the next pass. At most one entry.",
    )

    @model_validator(mode="after")
    def _cap_notepad(self) -> Self:
        if len(self.notepad) <= 1:
            return self
        return self.model_copy(update={"notepad": self.notepad[:1]})


# ─── Prompt-input shapes ────────────────────────────────


class GlossaryCharacterRef(BaseModel):
    """Character entries from the glossary (status != rejected) — sent
    in to the prompt as the closed set of eligible speakers.

    Distinct from the voice-extraction GlossaryCharacterRef (which
    carries an extra ``has_voice_profile`` flag); Pass 1 doesn't care
    about voice-profile state.
    """

    glossary_entry_id: str
    canonical_name: str
    variants: list[str] = Field(default_factory=list)
