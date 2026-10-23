"""Schema for the speaker-attribution step (Pass 1).

Paired with ``../prompts/identify_speakers_prompt.py``.

What this step does
-------------------
The code finds dialogue paragraphs (``services.dialogue_lines``) and
numbers them ``L1…Ln`` within a chunk of one chapter. For each numbered
line the model says what kind of line it is, who says it and to whom.

Why the code finds the lines
----------------------------
The model never copies text, so no line can be invented or misquoted,
and no line is skipped silently: every numbered line gets a row, and a
line the model leaves out is stored as ``unknown``.

Short character codes
---------------------
Characters are listed as ``C1…Cn``. The model returns the code plus the
canonical name; the validator drops a speaker whose code and name
disagree (same cross-check as before, without spending ~20 output
tokens per UUID on a book with 1,700 lines).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LineKind = Literal["speech", "thought", "not_dialogue"]
Confidence = Literal["clear", "inferred"]


class LineAttribution(BaseModel):
    """Who says one numbered line, and to whom."""

    line: int = Field(description="The line number, without the L. Example: 12 for L12.")
    kind: LineKind = Field(
        description=(
            "speech: said aloud. thought: inner speech or a remembered "
            "line. not_dialogue: a title, sign, letter, quoted phrase or "
            "narration that only looks like dialogue."
        ),
    )
    speaker_code: str | None = Field(
        default=None,
        description=(
            "Character code from the list (C3). Null when the speaker is "
            "not in the list, cannot be worked out, or kind is not_dialogue."
        ),
    )
    speaker_name: str | None = Field(
        default=None,
        description="Canonical name for speaker_code, copied from the list.",
    )
    addressee_code: str | None = Field(
        default=None,
        description=(
            "Code of the character spoken to. Null when unclear, a group, or not in the list."
        ),
    )
    addressee_name: str | None = Field(
        default=None,
        description="Canonical name for addressee_code, copied from the list.",
    )
    confidence: Confidence = Field(
        description=(
            "clear: a speech tag or the narration names the speaker. "
            "inferred: worked out from turn order or context."
        ),
    )
    mixed: bool = Field(
        default=False,
        description="True when two characters speak in this one line.",
    )


class ChunkAttribution(BaseModel):
    """Pass 1's output for one chunk."""

    scene: str = Field(
        description=(
            "One or two sentences: who is present and who talks to whom. "
            "Write this first. Not stored."
        ),
    )
    lines: list[LineAttribution] = Field(
        default_factory=list,
        description="One entry per numbered line, in order.",
    )


# ─── Prompt-input shapes ────────────────────────────────


class GlossaryCharacterRef(BaseModel):
    """A glossary character (status not inactive), with its code for this run."""

    code: str
    glossary_entry_id: str
    canonical_name: str
    variants: list[str] = Field(default_factory=list)
