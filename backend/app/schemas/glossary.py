"""API contracts for the working glossary (author review)."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GlossaryWorkingEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    canonical_form: str
    term_type: str
    meaning: str
    translation_recommendation: dict[str, Any]
    variants: list[str] = Field(default_factory=list)
    status: str
    first_seen_window: int
    occurrence_count: int
    created_at: datetime
    updated_at: datetime


class GlossaryRunMetaOut(BaseModel):
    id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    model: str | None
    entry_count: int


class GlossarySelectOptionOut(BaseModel):
    """One allowed value for a glossary enum, for client selects and filters."""

    id: str
    label: str


class WorkingGlossaryResponse(BaseModel):
    """Latest extraction run for the book and its working ``GlossaryEntry`` rows."""

    run: GlossaryRunMetaOut | None = None
    entries: list[GlossaryWorkingEntryOut] = Field(default_factory=list)
    term_type_options: list[GlossarySelectOptionOut] = Field(default_factory=list)
    translation_suggestion_options: list[GlossarySelectOptionOut] = Field(
        default_factory=list,
    )


class GlossaryWorkingEntryPatchIn(BaseModel):
    """Author updates to one working glossary row (persisted on ``GlossaryEntry``)."""

    proposed_target: str | None = None
    suggestion: Literal["keep_original", "translate"] | None = None
    accept: bool = False
    reject: bool = False
    merge_into_entry_id: UUID | None = None

    @model_validator(mode="after")
    def _exclusive_and_nonempty(self) -> Self:
        merge = self.merge_into_entry_id is not None
        rej = self.reject
        acc = self.accept
        trans = self.proposed_target is not None or self.suggestion is not None

        if merge and (rej or acc or trans):
            raise ValueError(
                "merge_into_entry_id cannot be combined with other patch fields.",
            )
        if rej and (merge or acc or trans):
            raise ValueError("reject cannot be combined with other patch fields.")
        if merge:
            return self
        if rej:
            return self
        if acc:
            return self
        if trans:
            return self
        raise ValueError(
            "Provide proposed_target and/or suggestion, set accept or reject, "
            "or set merge_into_entry_id.",
        )
