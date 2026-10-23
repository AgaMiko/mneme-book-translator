"""API contracts for fragment translation (Step 5)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID  # noqa: TC003 - pydantic needs it at runtime

from pydantic import BaseModel, Field

TranslationRunStatus = Literal["running", "completed", "failed", "cancelled"]
TranslationStage = Literal["faithful", "line_edit", "polish"]


class TranslationRunOut(BaseModel):
    id: str
    status: TranslationRunStatus
    cancel_requested: bool
    chapter_ids: list[str] | None
    fragments_total: int
    fragments_completed: int
    fragments_failed: int
    models: dict[str, str]
    error_message: str | None
    started_at: str
    completed_at: str | None


class ParagraphTextOut(BaseModel):
    paragraph_id: str
    text: str


class StageOut(BaseModel):
    paragraphs: list[ParagraphTextOut]
    notes: list[dict[str, Any]] = Field(default_factory=list)
    declared_edits: list[dict[str, Any]] = Field(default_factory=list)
    qa: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    model: str | None
    created_at: str


class FragmentRunStatusOut(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    last_stage: TranslationStage | None
    error_message: str | None


class FragmentOut(BaseModel):
    fragment_id: str
    position: int
    paragraph_ids: list[str]
    word_count: int
    run_status: FragmentRunStatusOut | None
    stages: dict[TranslationStage, StageOut]


class ChapterTranslationOut(BaseModel):
    chapter_id: str
    fragments: list[FragmentOut]
    metrics: dict[TranslationStage, dict[str, Any]]


class TranslationViewResponse(BaseModel):
    run: TranslationRunOut | None
    fragment_count: int
    chapters: list[ChapterTranslationOut]


class StartTranslationIn(BaseModel):
    chapter_ids: list[UUID] | None = Field(
        default=None, description="Chapters to translate. Omit for the whole book."
    )
    retranslate: bool = Field(
        default=False,
        description="Also translate fragments that already have a polished translation.",
    )
    model: str | None = Field(
        default=None,
        description="Model for every stage of this run. Omit for the configured models.",
    )


class TranslationStageEstimateOut(BaseModel):
    stage: TranslationStage
    model: str
    thinking: str | None = Field(default=None, description="Thinking level, or None for default.")
    stored_as: TranslationStage = Field(
        description="The stage this call's text is saved as (two-step mode saves the revision "
        "as the final stage)."
    )
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class TranslationEstimateOut(BaseModel):
    service_tier: str | None = Field(default=None, description="OpenAI service tier, e.g. flex.")
    word_count: int
    fragment_count: int
    glossary_terms: int
    total_tokens: int
    cost_usd: float
    stages: list[TranslationStageEstimateOut]


class GlossaryTermOut(BaseModel):
    id: str
    source: str
    target: str
    term_type: str
    note: str | None


class TermSpanOut(BaseModel):
    term_id: str
    start: int
    end: int


class TranslationTermsResponse(BaseModel):
    terms: list[GlossaryTermOut]
    paragraphs: dict[str, list[TermSpanOut]]
