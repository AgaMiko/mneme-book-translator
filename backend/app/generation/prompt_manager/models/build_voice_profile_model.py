"""Schema for building voice profiles from all of a character's lines.

Paired with ``../prompts/build_voice_profile_prompt.py``.

One call sees every speech line of one character (or of a few
characters with only a handful of lines each), numbered ``L1…Ln``
across the call. It returns, per character:

- ``features`` — each voice feature with the line numbers that show it.
  The validator drops line numbers that are not this character's, and
  drops a feature left with none.
- ``register_shifts`` — how the voice changes with the addressee or the
  situation, also with line numbers.
- ``source_voice_observation`` and ``target_voice_strategy`` — the two
  fields translation reads, same meaning as before.
- ``reference_passages`` — line ranges; the code cuts the passage text
  from the paragraphs, including other speakers' lines in between.

This replaces the window-by-window extraction, the candidate pool and
the separate passage-selection call.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceFeature(BaseModel):
    feature: str = Field(
        description=(
            "One concrete feature of how the character speaks, in the target "
            "language, naming the source marker (a particle, a tic, an error, "
            "a register)."
        ),
    )
    lines: list[int] = Field(
        description="Line numbers (without the L) that show it. At least one; up to five.",
    )


class RegisterShift(BaseModel):
    situation: str = Field(
        description="Who they speak to or what is happening, e.g. 'to her father', 'under stress'.",
    )
    change: str = Field(description="How the voice changes there.")
    lines: list[int] = Field(description="Line numbers that show it.")


class ReferencePassagePick(BaseModel):
    first_line: int = Field(description="First line number of the passage.")
    last_line: int = Field(
        description=(
            "Last line number of the passage; the same as first_line for a "
            "single line. Pick lines from one scene; the passage includes "
            "everything between them."
        ),
    )
    why: str = Field(description="One short clause: what this passage shows of the voice.")


class CharacterProfileDraft(BaseModel):
    character_code: str = Field(description="Code from the character heading (C3).")
    character_name: str = Field(description="Canonical name from the heading. Copy verbatim.")
    features: list[VoiceFeature] = Field(default_factory=list)
    register_shifts: list[RegisterShift] = Field(default_factory=list)
    source_voice_observation: str = Field(
        description=(
            "What the character is really doing in the source language, written "
            "in the target language. Built from the features above."
        ),
    )
    target_voice_strategy: str = Field(
        description=(
            "Translation guidance: source trigger → MIRROR / RECAST / WATCH, "
            "written in the target language."
        ),
    )
    reference_passages: list[ReferencePassagePick] = Field(default_factory=list)


class VoiceProfiles(BaseModel):
    """Output of one profile-building call."""

    profiles: list[CharacterProfileDraft] = Field(
        default_factory=list,
        description="One profile per character in the input, in input order.",
    )
