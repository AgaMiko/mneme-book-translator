"""API contracts for the working glossary (author review)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
