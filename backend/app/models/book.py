"""ORM models for the manuscript domain.

Hierarchy:
    Book → Chapter → Paragraph

Paragraphs hold the raw source text. Once the pipeline lands they will
be further partitioned into translation Fragments, but for the upload-
and-display slice paragraphs are sufficient and keep the schema clean.

Foreign-key columns and back-populating relationships are `init=False`:
they're set by SQLAlchemy when you append to the parent's collection.
This keeps construction call sites clean — you build a Book by passing
its `chapters` list and never have to touch FKs by hand.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base
from app.models.glossary import FinalGlossary, GlossaryEntry, GlossaryExtractionRun

if TYPE_CHECKING:
    from app.models.speakers import WindowSpeaker
    from app.models.voice import CharacterVoice


class Book(Base):
    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))

    # LLM-extracted metadata. All optional — populated asynchronously after
    # upload finishes. ``metadata_status`` drives the frontend's polling:
    # while it is "pending" the reader shows an "extracting metadata…" pill
    # and TanStack Query keeps polling; "ready" or "failed" stops polling.
    author: Mapped[str | None] = mapped_column(String(500), default=None)
    source_language: Mapped[str] = mapped_column(String(8), default="pl")
    target_language: Mapped[str] = mapped_column(String(8), default="en")
    manuscript_language: Mapped[str | None] = mapped_column(String(64), default=None)
    language_style_note: Mapped[str | None] = mapped_column(Text, default=None)
    metadata_model: Mapped[str | None] = mapped_column(String(128), default=None)
    metadata_status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        server_default="pending",
    )

    word_count: Mapped[int] = mapped_column(Integer, default=0)

    # Async glossary extraction lifecycle (poll from the reader like metadata).
    glossary_extraction_status: Mapped[str] = mapped_column(
        String(16),
        default="idle",
        server_default="idle",
    )
    glossary_extraction_cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    glossary_extraction_windows_total: Mapped[int | None] = mapped_column(Integer, default=None)
    glossary_extraction_windows_completed: Mapped[int | None] = mapped_column(Integer, default=None)

    speakers_extraction_status: Mapped[str] = mapped_column(
        String(16),
        default="idle",
        server_default="idle",
    )
    speakers_extraction_cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    speakers_extraction_windows_total: Mapped[int | None] = mapped_column(Integer, default=None)
    speakers_extraction_windows_completed: Mapped[int | None] = mapped_column(Integer, default=None)
    speakers_extraction_last_error: Mapped[str | None] = mapped_column(Text, default=None)

    voice_extraction_status: Mapped[str] = mapped_column(
        String(16),
        default="idle",
        server_default="idle",
    )
    voice_extraction_cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    voice_extraction_windows_total: Mapped[int | None] = mapped_column(Integer, default=None)
    voice_extraction_windows_completed: Mapped[int | None] = mapped_column(Integer, default=None)
    voice_extraction_last_error: Mapped[str | None] = mapped_column(Text, default=None)

    # Which published glossary downstream translation should use (immutable
    # ``FinalGlossary`` + ``FinalGlossaryEntry`` rows). Working drafts live in
    # ``GlossaryEntry`` for the relevant ``GlossaryExtractionRun``.
    active_final_glossary_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("final_glossaries.id", ondelete="SET NULL"),
        default=None,
    )

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

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="Chapter.position",
        default_factory=list,
        init=False,
    )
    glossary_extraction_runs: Mapped[list[GlossaryExtractionRun]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )
    glossary_entries: Mapped[list[GlossaryEntry]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )
    final_glossaries: Mapped[list[FinalGlossary]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        foreign_keys=[FinalGlossary.book_id],
        default_factory=list,
        init=False,
    )
    active_final_glossary: Mapped[FinalGlossary | None] = relationship(
        "FinalGlossary",
        foreign_keys=[active_final_glossary_id],
        primaryjoin="Book.active_final_glossary_id == FinalGlossary.id",
        uselist=False,
        overlaps="book,final_glossaries",
        init=False,
    )
    character_voices: Mapped[list[CharacterVoice]] = relationship(
        "CharacterVoice",
        back_populates="book",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )
    window_speakers: Mapped[list[WindowSpeaker]] = relationship(
        "WindowSpeaker",
        back_populates="book",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "position", name="uq_chapter_position"),)

    position: Mapped[int] = mapped_column(Integer)

    title: Mapped[str | None] = mapped_column(String(500), default=None)

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        init=False,
    )
    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    book: Mapped[Book] = relationship(back_populates="chapters", init=False)
    paragraphs: Mapped[list[Paragraph]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Paragraph.position",
        default_factory=list,
    )


class Paragraph(Base):
    __tablename__ = "paragraphs"
    __table_args__ = (UniqueConstraint("chapter_id", "position", name="uq_paragraph_position"),)

    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    style: Mapped[str | None] = mapped_column(String(64), default=None)

    chapter_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        init=False,
    )
    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )

    chapter: Mapped[Chapter] = relationship(back_populates="paragraphs", init=False)
