"""Schema for the first-pass manuscript metadata extraction step."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ManuscriptMetadata(BaseModel):
    """Metadata inferred from a manuscript opening sample.

    Field order is deliberate: language is the broadest signal and grounds
    the rest of the extraction. Author and title come next as surface-level
    facts. The style note depends on all of the above and therefore sits
    last so the model has full context when writing it.
    """

    manuscript_language: str = Field(
        max_length=64,
        description="Natural-language name of the source language (e.g. 'Polish', 'English').",
    )
    author: str | None = Field(
        default=None,
        max_length=500,
        description="Author name if visible in the sample; null when absent.",
    )
    book_title: str | None = Field(
        default=None,
        max_length=500,
        description="Book title if visible in the sample; null when absent.",
    )
    language_style_note: str = Field(
        max_length=800,
        description=(
            "One or two sentences naming the prose register, voice, and any texture "
            "a literary translator should keep in mind."
        ),
    )

    @field_validator("author", "book_title", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value
