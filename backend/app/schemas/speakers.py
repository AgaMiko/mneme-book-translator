"""API contracts for Pass 1 speaker attribution (read-only review)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID  # noqa: TC003 - pydantic needs it at runtime

from pydantic import BaseModel, Field


class AddresseeCountOut(BaseModel):
    """How many of a character's speech lines go to one addressee."""

    glossary_entry_id: UUID
    canonical_name: str
    line_count: int


class CharacterSpeakerMapOut(BaseModel):
    """Per-character rollup of Pass 1 results."""

    glossary_entry_id: UUID
    canonical_name: str
    line_count: int = Field(description="Speech lines.")
    thought_count: int = 0
    speech_words: int = 0
    chapters: list[int] = Field(
        default_factory=list,
        description="Chapter numbers (1-based, book order) with speech lines.",
    )
    windows: list[int] = Field(
        default_factory=list,
        description="Voice-extraction windows with speech lines (used by Pass 2).",
    )
    addressees: list[AddresseeCountOut] = Field(default_factory=list)


class WorkingSpeakersResponse(BaseModel):
    """Speaker attribution for a book — updates as Pass 1 chunks complete."""

    entries: list[CharacterSpeakerMapOut] = Field(default_factory=list)
    lines_total: int = 0
    lines_attributed: int = Field(default=0, description="Speech and thought lines with a speaker.")
    lines_unknown: int = Field(
        default=0, description="Dialogue lines with no speaker from the glossary."
    )
    lines_not_dialogue: int = 0


class DialogueLineOut(BaseModel):
    paragraph_id: UUID
    line_index: int
    chapter_number: int = Field(description="1-based, book order.")
    chapter_title: str | None = None
    text: str
    kind: str
    speaker_name: str | None = None
    addressee_name: str | None = None
    confidence: str | None = None


class DialogueLinesResponse(BaseModel):
    lines: list[DialogueLineOut] = Field(default_factory=list)
    truncated: bool = False


class ManuscriptSpeakerLineOut(BaseModel):
    """Who says one dialogue paragraph, for the manuscript's speaker layer."""

    paragraph_id: UUID
    kind: str
    speaker_id: UUID | None = None
    speaker_name: str | None = None
    addressee_name: str | None = None
    confidence: str | None = None
    mixed: bool = False


class ManuscriptSpeakersResponse(BaseModel):
    lines: list[ManuscriptSpeakerLineOut] = Field(default_factory=list)


class NarrationSceneOut(BaseModel):
    """One scene and whose point of view its narration follows."""

    chapter_id: UUID
    pov_name: str | None = None
    pov_id: UUID | None = Field(default=None, description="Glossary character, when matched.")
    source: Literal["heading", "scene_break", "assumed", "unknown"] = Field(
        description="heading / scene_break: named by the author. assumed: an unnamed scene "
        "break, POV carried over from the chapter heading. unknown: no marker."
    )
    paragraph_ids: list[UUID] = Field(default_factory=list)


class NarrationPovResponse(BaseModel):
    scenes: list[NarrationSceneOut] = Field(default_factory=list)
