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


class VoiceWorkingProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    glossary_entry_id: UUID
    canonical_name: str
    source_voice_observation: str
    target_voice_strategy: str
    # Legacy: primary passage (lowest selection_rank) for old clients / quick scan.
    reference_passage_source: str
    reference_passage_translation_proposed: str
    reference_passage_translation_authoritative: str | None
    selected_passages: list[VoiceSelectedPassageOut] = Field(default_factory=list)
    status: str
    dialogue_volume_observed: int
    first_seen_window: int
    last_observed_window: int
    created_at: datetime
    updated_at: datetime


class WorkingVoicesResponse(BaseModel):
    entries: list[VoiceWorkingProfileOut] = Field(default_factory=list)


class VoiceWorkingProfilePatchIn(BaseModel):
    """Author review: accept, reject, or send edits (adjust).

    - **accept** — approve both summary and the model’s translation; authoritative
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
    reference_passage_translation: str | None = None

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
                self.reference_passage_translation,
            )
        )
        if acc or rej:
            if has_edits:
                raise ValueError("accept/reject cannot be combined with edit fields.")
            return self
        if has_edits:
            return self
        raise ValueError(
            "Set accept, reject, or provide at least one of source_voice_observation, "
            "target_voice_strategy, or reference_passage_translation.",
        )
