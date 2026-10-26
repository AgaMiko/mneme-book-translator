"""API contracts for character voice profiles (author review)."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VoiceSelectedPassageOut(BaseModel):
    """One final reference passage (after selection + translation pass)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    selection_rank: int
    source_text: str
    why_selected: str
    translation_proposed: str | None
    translation_authoritative: str | None
    status: str
    # Cast pass: why the proposed English loses this voice, and a revision.
    translation_review: str | None = None
    translation_revised: str | None = None


class VoiceEvidenceLineOut(BaseModel):
    """A dialogue line cited as evidence for a feature."""

    paragraph_id: UUID
    chapter_number: int
    text: str


class VoiceFeatureOut(BaseModel):
    feature: str
    lines: list[VoiceEvidenceLineOut] = Field(default_factory=list)


class VoiceRegisterShiftOut(BaseModel):
    situation: str
    change: str
    lines: list[VoiceEvidenceLineOut] = Field(default_factory=list)


class VoiceWorkingProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    glossary_entry_id: UUID
    canonical_name: str
    source_voice_observation: str
    target_voice_strategy: str
    # Short rules from the cast pass; what translation sends when set.
    translation_brief: str | None = None
    # Legacy: primary passage (lowest selection_rank) for old clients / quick scan.
    reference_passage_source: str
    reference_passage_translation_proposed: str
    reference_passage_translation_authoritative: str | None
    selected_passages: list[VoiceSelectedPassageOut] = Field(default_factory=list)
    status: str
    needs_regeneration: bool = False
    dialogue_volume_observed: int
    first_seen_window: int
    last_observed_window: int
    # Profiles built from all of the character's lines.
    line_count: int = 0
    low_evidence: bool = False
    lines_sampled: bool = False
    features: list[VoiceFeatureOut] = Field(default_factory=list)
    register_shifts: list[VoiceRegisterShiftOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkingVoicesResponse(BaseModel):
    entries: list[VoiceWorkingProfileOut] = Field(default_factory=list)


class VoiceWorkingProfilePatchIn(BaseModel):
    """Author review: accept, reject, or send edits (adjust).

    - **accept** — approve both summary and the model's translation; authoritative
      translation is set to the proposed text.
    - **reject** — dismiss the profile; no authoritative translation.
    - **Edits** — provide ``source_voice_observation`` and/or
      ``target_voice_strategy`` and/or ``reference_passage_translation``
      without accept/reject to record adjustments (``adjusted``). At least one
      field must be non-null.
    """

    accept: bool = False
    reject: bool = False
    source_voice_observation: str | None = None
    target_voice_strategy: str | None = None
    translation_brief: str | None = None
    reference_passage_translation: str | None = None
    selected_passage_id: UUID | None = None
    selected_passage_translation: str | None = None
    needs_regeneration: bool | None = None

    @model_validator(mode="after")
    def _exclusive(self) -> Self:
        acc, rej = self.accept, self.reject
        if acc and rej:
            raise ValueError("Cannot set both accept and reject.")
        has_edits = any(
            v is not None
            for v in (
                self.source_voice_observation,
                self.target_voice_strategy,
                self.translation_brief,
                self.reference_passage_translation,
                self.selected_passage_translation,
                self.needs_regeneration,
            )
        )
        if self.selected_passage_id is not None and self.selected_passage_translation is None:
            raise ValueError(
                "selected_passage_id requires selected_passage_translation.",
            )
        if self.selected_passage_id is None and self.selected_passage_translation is not None:
            raise ValueError("Passage edits require selected_passage_id.")
        if acc or rej:
            if has_edits:
                raise ValueError("accept/reject cannot be combined with edit fields.")
            return self
        if has_edits:
            return self
        raise ValueError(
            "Set accept, reject, or provide at least one of source_voice_observation, "
            "target_voice_strategy, reference_passage_translation, or passage edits.",
        )
