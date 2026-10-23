"""API contracts for the working glossary (author review)."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    # Set while the status is an automatic decision the author has not
    # confirmed or undone: ``action`` (merge / accept / reject) and ``reason``.
    auto_review: dict[str, Any] | None = None
    merged_into_id: UUID | None = None

    @field_validator("auto_review")
    @classmethod
    def _hide_undone(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        # An undone decision is only a marker for the server; to the author
        # the row is an ordinary pending term again.
        return None if v is None or v.get("undone") else v


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
    # Make an automatic decision the author's own, or put the term back to pending.
    confirm_auto: bool = False
    undo_auto: bool = False

    @model_validator(mode="after")
    def _exclusive_and_nonempty(self) -> Self:
        if self.confirm_auto or self.undo_auto:
            others = (
                self.merge_into_entry_id is not None
                or self.reject
                or self.accept
                or self.proposed_target is not None
                or self.suggestion is not None
            )
            if others or (self.confirm_auto and self.undo_auto):
                raise ValueError("confirm_auto and undo_auto cannot be combined with other fields.")
            return self
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


class GlossaryImportSourceOut(BaseModel):
    """Another book whose glossary has reviewed terms that can be imported."""

    book_id: UUID
    title: str | None
    original_filename: str | None
    created_at: datetime
    accepted: int
    removed: int


class GlossaryImportSourcesResponse(BaseModel):
    sources: list[GlossaryImportSourceOut]


class GlossaryImportIn(BaseModel):
    source_book_id: UUID


class GlossaryImportResponse(BaseModel):
    """Counts: new terms, proposals replaced by the other book's decision,
    and terms already reviewed here (kept, variants combined)."""

    added: int
    updated: int
    kept: int
