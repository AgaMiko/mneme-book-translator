"""ORM models for fragment translation (Step 5).

Layers
------
- ``TranslationFragment`` — a contiguous run of paragraphs inside one
  chapter (about 1,200 source words). Computed once per book from paragraph
  word counts; the unit of LLM work.
- ``TranslationRun`` — one pass over the book (or over selected chapters).
  Carries the polling contract the reader uses (status, cancel flag,
  fragment counters), like the glossary/voice runs keep on ``Book``.
- ``TranslationRunFragment`` — per-run status of one fragment (which stage
  it reached, last error).
- ``FragmentRendition`` — the output of one stage (faithful, line_edit,
  polish) for one fragment in one run. Paragraph-aligned: ``paragraphs`` is
  a list of ``{"paragraph_id", "text"}`` with exactly the fragment's ids in
  order. All three stages are kept so the author can compare them.

See ``docs/step5-translation-pipeline.md`` for the full design. This is the
first slice: no flags table, glossary propagation or export yet.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves Mapped[] at runtime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
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

TRANSLATION_STAGES: tuple[str, ...] = ("faithful", "line_edit", "polish")


class TranslationFragment(Base):
    """A contiguous run of paragraphs within one chapter."""

    __tablename__ = "translation_fragments"
    __table_args__ = (
        UniqueConstraint("book_id", "position", name="uq_translation_fragment_position"),
    )

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        index=True,
    )
    chapter_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        index=True,
    )
    # Book-wide order (0-based).
    position: Mapped[int] = mapped_column(Integer)
    paragraph_ids: Mapped[list[UUID]] = mapped_column(ARRAY(SA_UUID(as_uuid=True)))
    word_count: Mapped[int] = mapped_column(Integer)
    # Offset of the first word in the book plaintext, same word split as the
    # glossary/speaker windows, so fragments map onto speaker windows.
    start_word_offset: Mapped[int] = mapped_column(Integer)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )


class TranslationRun(Base):
    """One translation pass over a book or over selected chapters."""

    __tablename__ = "translation_runs"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        index=True,
    )
    # running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # NULL = whole book.
    chapter_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(SA_UUID(as_uuid=True)), default=None
    )
    fragments_total: Mapped[int] = mapped_column(Integer, default=0)
    fragments_completed: Mapped[int] = mapped_column(Integer, default=0)
    fragments_failed: Mapped[int] = mapped_column(Integer, default=0)
    # {"faithful": "...", "line_edit": "...", "polish": "..."}
    models: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    run_fragments: Mapped[list[TranslationRunFragment]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        default_factory=list,
        init=False,
    )


class TranslationRunFragment(Base):
    """Status of one fragment within one run."""

    __tablename__ = "translation_run_fragments"
    __table_args__ = (
        UniqueConstraint("run_id", "fragment_id", name="uq_translation_run_fragment"),
    )

    run_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("translation_runs.id", ondelete="CASCADE"),
        index=True,
    )
    fragment_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("translation_fragments.id", ondelete="CASCADE"),
        index=True,
    )
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    # Last stage that produced a rendition (None before the first).
    last_stage: Mapped[str | None] = mapped_column(String(16), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )

    run: Mapped[TranslationRun] = relationship(back_populates="run_fragments", init=False)


class FragmentRendition(Base):
    """Output of one stage for one fragment in one run."""

    __tablename__ = "fragment_renditions"
    __table_args__ = (
        UniqueConstraint("run_id", "fragment_id", "stage", name="uq_fragment_rendition_stage"),
    )

    run_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("translation_runs.id", ondelete="CASCADE"),
        index=True,
    )
    fragment_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("translation_fragments.id", ondelete="CASCADE"),
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(16))
    # [{"paragraph_id": "<uuid>", "text": "..."}], in fragment order.
    paragraphs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Translator notes, declared edits, QA metrics for this stage.
    notes: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    usage_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
