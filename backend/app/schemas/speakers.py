"""API contracts for Pass 1 speaker map (read-only review)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class SpeakerWindowOut(BaseModel):
    """One window where a character was identified as speaking."""

    window_number: int
    quoted_evidence: str


class CharacterSpeakerMapOut(BaseModel):
    """Per-character rollup of Pass 1 results."""

    glossary_entry_id: UUID
    canonical_name: str
    windows: list[int] = Field(
        description="Sorted window numbers where this character speaks.",
    )
    appearances: list[SpeakerWindowOut] = Field(
        default_factory=list,
        description="One row per window (same order as ``windows``).",
    )


class WorkingSpeakersResponse(BaseModel):
    """Speaker map for a book — updates as Pass 1 windows complete."""

    entries: list[CharacterSpeakerMapOut] = Field(default_factory=list)
    windows_mapped: int = Field(
        description="Count of distinct windows with at least one speaker.",
    )
    edges_total: int = Field(
        description="Total (character, window) edges stored.",
    )
