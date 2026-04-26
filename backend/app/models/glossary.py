"""ORM models for the persisted glossary pipeline.

Layers
------
- **Extraction artifacts** — ``GlossaryExtractionRun`` + ``GlossaryWindowGeneration``
  retain every raw model delta (JSON) per window so runs are auditable and
  reproducible without re-calling the LLM.
- **Working glossary** — ``GlossaryEntry`` rows scoped to a run; author
  workflow (``proposed`` / ``accepted`` / ``adjusted`` / ``rejected``) applies
  here. Translation *review* reads this set for the active completed run.
- **Final glossary** — ``FinalGlossary`` + ``FinalGlossaryEntry`` are an
  immutable snapshot promoted from reviewed working rows. Later pipeline
  steps (fragment translation, consistency checks) should read **only** the
  book's ``active_final_glossary`` (see ``Book.active_final_glossary_id``),
  not live ``GlossaryEntry`` rows.

Distinct from
-------------
- ``app.generation.prompt_manager.models.extract_glossary_model`` — LLM I/O.
- ``app.schemas.glossary`` — API DTOs for the review UI.

The LLM never sees ``status`` on working entries — that stays FE/BE territory.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.book import Book


class GlossaryExtractionRun(Base):
    """One end-to-end extraction pass over a book (all windows).

    Raw per-window payloads live in ``GlossaryWindowGeneration``. Working
    ``GlossaryEntry`` rows created during this run reference ``id`` here.
    """

    __tablename__ = "glossary_extraction_runs"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default="running",
        server_default="running",
    )
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    book: Mapped[Book] = relationship(back_populates="glossary_extraction_runs", init=False)
    window_generations: Mapped[list[GlossaryWindowGeneration]] = relationship(
        back_populates="extraction_run",
        cascade="all, delete-orphan",
        order_by="GlossaryWindowGeneration.window_number",
        default_factory=list,
        init=False,
    )
    glossary_entries: Mapped[list[GlossaryEntry]] = relationship(
        back_populates="extraction_run",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )
    notepad: Mapped[GlossaryNotepad | None] = relationship(
        back_populates="extraction_run",
        cascade="all, delete-orphan",
        uselist=False,
        init=False,
    )
    final_glossaries_sourced_from: Mapped[list[FinalGlossary]] = relationship(
        back_populates="source_extraction_run",
        foreign_keys="FinalGlossary.source_extraction_run_id",
        default_factory=list,
        init=False,
    )


class GlossaryWindowGeneration(Base):
    """Immutable record of one window's raw ``GlossaryUpdate`` JSON."""

    __tablename__ = "glossary_window_generations"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "window_number",
            name="uq_glossary_window_run_number",
        ),
    )

    extraction_run_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
        index=True,
    )
    window_number: Mapped[int] = mapped_column(Integer)
    raw_response: Mapped[dict] = mapped_column(JSONB)
    usage_metadata: Mapped[dict | None] = mapped_column(JSONB, default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    extraction_run: Mapped[GlossaryExtractionRun] = relationship(
        back_populates="window_generations", init=False
    )


class GlossaryEntry(Base):
    """Working glossary row for one extraction run (author review)."""

    __tablename__ = "glossary_entries"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "canonical_form",
            name="uq_glossary_run_canonical",
        ),
    )

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        index=True,
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
        index=True,
    )

    canonical_form: Mapped[str] = mapped_column(String(200))
    term_type: Mapped[str] = mapped_column(String(32))
    meaning: Mapped[str] = mapped_column(Text)

    translation_recommendation: Mapped[dict] = mapped_column(JSONB)

    variants: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)

    status: Mapped[str] = mapped_column(
        String(16), default="proposed", server_default="proposed"
    )

    first_seen_window: Mapped[int] = mapped_column(Integer)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )

    book: Mapped[Book] = relationship(back_populates="glossary_entries", init=False)
    extraction_run: Mapped[GlossaryExtractionRun] = relationship(
        back_populates="glossary_entries", init=False
    )


class GlossaryNotepad(Base):
    """Scratchpad state for one extraction run (replaced each window)."""

    __tablename__ = "glossary_notepads"

    extraction_run_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    notes: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    last_window_number: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )

    extraction_run: Mapped[GlossaryExtractionRun] = relationship(
        back_populates="notepad", init=False
    )


class FinalGlossary(Base):
    """Frozen glossary snapshot handed off to downstream translation."""

    __tablename__ = "final_glossaries"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        index=True,
    )
    source_extraction_run_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_extraction_runs.id", ondelete="SET NULL"),
        default=None,
    )
    label: Mapped[str] = mapped_column(String(200), default="default", server_default="default")

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    book: Mapped[Book] = relationship(
        back_populates="final_glossaries",
        foreign_keys=[book_id],
        overlaps="active_final_glossary",
        init=False,
    )
    source_extraction_run: Mapped[GlossaryExtractionRun | None] = relationship(
        back_populates="final_glossaries_sourced_from",
        foreign_keys=[source_extraction_run_id],
        init=False,
    )
    entries: Mapped[list[FinalGlossaryEntry]] = relationship(
        back_populates="final_glossary",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )


class FinalGlossaryEntry(Base):
    """One term in the published glossary — stable contract for later steps."""

    __tablename__ = "final_glossary_entries"
    __table_args__ = (
        UniqueConstraint(
            "final_glossary_id",
            "canonical_form",
            name="uq_final_glossary_canonical",
        ),
    )

    final_glossary_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("final_glossaries.id", ondelete="CASCADE"),
        index=True,
    )
    source_glossary_entry_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_entries.id", ondelete="SET NULL"),
        default=None,
    )

    canonical_form: Mapped[str] = mapped_column(String(200))
    term_type: Mapped[str] = mapped_column(String(32))
    meaning: Mapped[str] = mapped_column(Text)
    variants: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    # Author-approved translation decision (same JSON shape as working
    # ``translation_recommendation`` — suggestion / proposed_target / rationale).
    translation: Mapped[dict] = mapped_column(JSONB)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    final_glossary: Mapped[FinalGlossary] = relationship(
        back_populates="entries", init=False
    )
