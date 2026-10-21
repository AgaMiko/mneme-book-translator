"""Schemas for the three fragment translation stages.

Paired with ``../prompts/translate_fragment_prompt.py``.

Every stage returns ``paragraphs``: one ``ParagraphOut`` per input paragraph,
same ids, same order. The prompt uses short ids (``p1``, ``p2``…); the
service maps them back to paragraph UUIDs and rejects any output whose ids
don't match.

Stage outputs
-------------
- ``FaithfulFragment`` — complete, accurate English; translator notes for the
  author (possible source typos, ambiguities, wordplay, placeholders).
- ``LineEditedFragment`` — the same text edited into natural English prose;
  any words added for clarity are listed as ``added_clarification`` notes.
- ``PolishedFragment`` — final polish against measured style targets; edits
  that might change meaning, remove a voice device, or fix continuity are
  declared in ``declared_edits`` so the author can review them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NoteKind = Literal[
    "source_typo",
    "continuity",
    "ambiguity",
    "wordplay",
    "placeholder",
    "added_clarification",
    "term_choice",
]


class ParagraphOut(BaseModel):
    paragraph_id: str = Field(
        description="The paragraph id from the input (p1, p2, ...). Copy it exactly."
    )
    text: str = Field(description="The English text of this paragraph.")


class TranslatorNote(BaseModel):
    paragraph_id: str = Field(description="Id of the paragraph the note is about.")
    kind: NoteKind = Field(
        description=(
            "source_typo: the source looks wrong and you translated what was probably meant. "
            "continuity: an inconsistency in the source, kept as written. "
            "ambiguity: more than one reading (including who is speaking); say which you chose. "
            "wordplay: a pun, name play or wording effect that could not be kept, or was adapted. "
            "placeholder: the author's unfinished text (e.g. xxxxxxx) copied as is. "
            "added_clarification: words you added that the source does not have. "
            "term_choice: a recurring name, nickname or term not in the glossary; say what you chose."
        )
    )
    note: str = Field(
        description=(
            "One or two plain sentences for the author: what the source says, what you did, "
            "and what the author should decide."
        )
    )


class FaithfulFragment(BaseModel):
    paragraphs: list[ParagraphOut]
    notes: list[TranslatorNote] = Field(
        default_factory=list,
        description="Only real questions for the author. Empty if there are none.",
    )


class LineEditedFragment(BaseModel):
    paragraphs: list[ParagraphOut]
    notes: list[TranslatorNote] = Field(
        default_factory=list,
        description=(
            "Every added clarifying beat as an added_clarification note, plus any new "
            "question for the author. Empty if there are none."
        ),
    )


class PolishEdit(BaseModel):
    paragraph_id: str
    kind: Literal["meaning_risk", "voice_device", "continuity"] = Field(
        description=(
            "meaning_risk: the edit may change what is said or what happens. "
            "voice_device: the edit removes or changes a deliberate voice feature "
            "(trailing ellipses, broken grammar, a verbal tic). "
            "continuity: the edit fixes a small inconsistency with the text around it."
        )
    )
    before: str = Field(description="The English phrase as it was in the line-edited text.")
    after: str = Field(description="The English phrase after your edit.")
    why: str = Field(description="One plain sentence.")


class PolishedFragment(BaseModel):
    paragraphs: list[ParagraphOut]
    declared_edits: list[PolishEdit] = Field(
        default_factory=list,
        description="Edits beyond style. Empty if every edit is purely stylistic.",
    )
    notes: list[TranslatorNote] = Field(
        default_factory=list,
        description="Lines you could not fix without changing meaning. Empty if none.",
    )
