"""Schemas for the cast pass: short briefs, then passage checks, with the whole cast in view.

Paired with ``../prompts/cast_voices_prompt.py``.

Profiles are built one character at a time, so nothing compares them.
The cast pass sees every profile together, in two calls: one writes the
briefs, the other (after the passages are translated with the briefs)
checks the passage translations. They return:

- ``cast_notes`` — which voices could collapse into one in the target
  language, and what keeps them apart. Written first; not stored.
- ``briefs`` — how each character should come across in the target
  language (voice, register, word choice), the only voice guidance
  translation sends.
- ``passage_flags`` — only passages whose proposed translation flattens
  the voice, breaks the brief or would pass for another character, each
  with a reason and a full revised translation for the author to accept.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PassageProblem = Literal["flattened", "sounds_like_other", "off_brief"]


class CharacterBrief(BaseModel):
    character_code: str = Field(description="Code from the character heading (C3).")
    character_name: str = Field(description="Canonical name from the heading. Copy verbatim.")
    brief: str = Field(
        description=(
            "About 100 words in the target language: 'Voice:' (who they sound like, "
            "vocabulary level, formality, how that sounds in the target language, and "
            "how they differ from the closest voice), then 'In their voice (style only, "
            "don't reuse phrases):' with two or three sentences spoken in their voice."
        ),
    )


class PassageFlag(BaseModel):
    passage: str = Field(description="Passage id from the input (P7).")
    problem: PassageProblem
    reason: str = Field(description="One or two sentences: what is wrong and where.")
    revised_translation: str = Field(
        description=(
            "The whole passage translated again, other speakers' lines included, "
            "fixing only the voice problem."
        ),
    )


class CastBriefs(BaseModel):
    """Output of the briefs call."""

    cast_notes: str = Field(
        description=(
            "Which characters could sound alike in the target language and what "
            "separates them. Write this first."
        ),
    )
    briefs: list[CharacterBrief] = Field(default_factory=list)


class PassageCheck(BaseModel):
    """Output of the passage-check call."""

    passage_flags: list[PassageFlag] = Field(default_factory=list)
