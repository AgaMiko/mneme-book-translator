"""ORM models for the speaker-identification stage (Pass 1).

Pass 1 runs *before* voice extraction. It attributes every dialogue
line of the book (found by ``services.dialogue_lines``) to a glossary
character, and records who the line is addressed to.

Structure
---------
- ``DialogueLine`` — one row per dialogue paragraph: kind (speech,
  thought, not dialogue), speaker, addressee. The source of truth.
- ``WindowSpeaker`` — one row per (book, window, character) edge,
  derived from ``DialogueLine`` when a run completes. Voice extraction
  and translation still read speakers per voice-extraction window;
  ``quoted_evidence`` holds the start of the character's first line in
  that window.
- ``SpeakerNotepad`` — notes from the earlier window-by-window Pass 1.
  No longer written; dropped in the voice-redesign cleanup.

Why no per-line status workflow
-------------------------------
Lines are not reviewed one by one. If Pass 1 mis-attributes lines, the
author resets and re-runs. Authorial review happens at the voice-profile
level (Pass 2 output).
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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


class WindowSpeaker(Base):
    """One (book, window, glossary_character) speaker edge.

    Inserted by Pass 1 when the model identifies a glossary character
    as having at least one quoted speaking line in the window.
    ``quoted_evidence`` is the verbatim phrase Pass 1 cited; the
    validator confirms it actually appears in the window text before
    persistence, so every row is grounded.
    """

    __tablename__ = "window_speakers"
    __table_args__ = (
        UniqueConstraint(
            "book_id",
            "window_number",
            "glossary_entry_id",
            name="uq_window_speaker_triple",
        ),
        Index(
            "ix_window_speakers_book_window",
            "book_id",
            "window_number",
        ),
        Index(
            "ix_window_speakers_book_character",
            "book_id",
            "glossary_entry_id",
        ),
    )

    window_number: Mapped[int] = mapped_column(Integer)
    quoted_evidence: Mapped[str] = mapped_column(Text)

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        init=False,
    )
    glossary_entry_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_entries.id", ondelete="CASCADE"),
        init=False,
    )
    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    book: Mapped["Book"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Book",
        back_populates="window_speakers",
        init=False,
    )
    glossary_entry: Mapped["GlossaryEntry"] = relationship(  # type: ignore[name-defined] # noqa: F821
        init=False,
    )


class SpeakerNotepad(Base):
    """Pass 1 notepad as it stood at the end of the last window.

    Mirror of ``VoiceNotepad``. One row per book; replaced each pass.
    Carries cross-window scratch notes — unresolved speakers,
    ambiguous attributions, patterns to watch.
    """

    __tablename__ = "speaker_notepads"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        primary_key=True,
    )
    notes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    last_window_number: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )


class DialogueLine(Base):
    """One dialogue paragraph and who says it.

    ``kind`` is ``speech``, ``thought`` or ``not_dialogue`` as Pass 1
    decided, or ``unknown`` when the model returned nothing usable for
    the line. ``speaker_glossary_entry_id`` is empty for unknown
    speakers and for characters not in the glossary.
    """

    __tablename__ = "dialogue_lines"
    __table_args__ = (
        UniqueConstraint("book_id", "paragraph_id", name="uq_dialogue_line_paragraph"),
        Index("ix_dialogue_lines_book_line", "book_id", "line_index"),
        Index("ix_dialogue_lines_book_speaker", "book_id", "speaker_glossary_entry_id"),
    )

    line_index: Mapped[int] = mapped_column(Integer)
    chunk_number: Mapped[int] = mapped_column(Integer)
    word_offset: Mapped[int] = mapped_column(Integer)
    marker: Mapped[str] = mapped_column(String(16))
    speech_text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        init=False,
    )
    paragraph_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("paragraphs.id", ondelete="CASCADE"),
        init=False,
    )
    speaker_glossary_entry_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_entries.id", ondelete="SET NULL"),
        default=None,
    )
    addressee_glossary_entry_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_entries.id", ondelete="SET NULL"),
        default=None,
    )
    confidence: Mapped[str | None] = mapped_column(String(16), default=None)
    mixed: Mapped[bool] = mapped_column(Boolean, default=False)
    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
