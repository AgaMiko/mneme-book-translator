"""API contracts for the book endpoints.

These are the shapes the *frontend* sees. They are deliberately
decoupled from `app.models` (persistence shape) so we can evolve
either layer without breaking the other.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Single source of truth for the metadata status enum. The DB column is a
# String for forward-compat (lets us add states without a migration), but
# the API contract is tight so the frontend can match against literals.
MetadataStatus = Literal["pending", "ready", "failed"]

GlossaryExtractionStatus = Literal[
    "idle",
    "running",
    "completed",
    "failed",
    "cancelled",
]

VoiceExtractionStatus = GlossaryExtractionStatus
SpeakersExtractionStatus = GlossaryExtractionStatus


class ParagraphResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    text: str
    style: str | None = None


class ChapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    title: str | None = None


class ChapterDetailResponse(ChapterResponse):
    paragraphs: list[ParagraphResponse] = Field(default_factory=list)


class BookSummary(BaseModel):
    """List-view shape — chapters and paragraphs not loaded."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    author: str | None = None
    source_language: str
    target_language: str
    manuscript_language: str | None = None
    language_style_note: str | None = None
    metadata_model: str | None = None
    metadata_status: MetadataStatus
    glossary_extraction_status: GlossaryExtractionStatus
    glossary_extraction_windows_total: int | None = None
    glossary_extraction_windows_completed: int | None = None
    voice_extraction_status: VoiceExtractionStatus
    voice_extraction_windows_total: int | None = None
    voice_extraction_windows_completed: int | None = None
    voice_extraction_last_error: str | None = None
    speakers_extraction_status: SpeakersExtractionStatus
    speakers_extraction_windows_total: int | None = None
    speakers_extraction_windows_completed: int | None = None
    speakers_extraction_last_error: str | None = None
    original_filename: str
    word_count: int
    created_at: datetime


class BookDetail(BookSummary):
    chapters: list[ChapterDetailResponse] = Field(default_factory=list)


class GlossaryExtractionStartResponse(BaseModel):
    """Returned when a glossary extraction job is accepted for background execution."""

    status: Literal["accepted"] = "accepted"
    book_id: UUID


class GlossaryExtractionStopResponse(BaseModel):
    """Returned when a cooperative cancel is queued for an in-flight extraction."""

    status: Literal["accepted"] = "accepted"
    book_id: UUID


class GlossaryExtractionEstimateResponse(BaseModel):
    """Predicted LLM usage for one full glossary extraction run."""

    model: str
    window_count: int
    window_words: int
    overlap_words: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    pricing_input_usd_per_mtok: float
    pricing_output_usd_per_mtok: float


class VoicePassEstimateResponse(BaseModel):
    """Predicted LLM usage for one voice pipeline pass."""

    window_count: int
    character_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float


class VoiceExtractionEstimateResponse(BaseModel):
    """Predicted LLM usage for speaker identification + voice extraction."""

    model: str
    window_words: int
    overlap_words: int
    character_count: int
    pass1: VoicePassEstimateResponse
    pass2: VoicePassEstimateResponse
    estimated_total_tokens: int
    estimated_cost_usd: float
    pricing_input_usd_per_mtok: float
    pricing_output_usd_per_mtok: float


class UploadBookResponse(BaseModel):
    """Returned immediately after upload. The book's content is fully
    parsed and persisted at this point. Metadata extraction continues
    asynchronously — the frontend should poll the book until
    ``metadata_status`` flips to ``"ready"`` or ``"failed"``.
    """

    book: BookSummary
    chapter_count: int
    paragraph_count: int
