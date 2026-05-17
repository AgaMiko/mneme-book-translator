"""ORM models for the speaker-identification stage (Pass 1).

Pass 1 runs *before* voice extraction and persists, for each manuscript
window, which glossary characters have at least one quoted speaking
line in that window. The resulting map has two downstream consumers:

- **Voice extraction (Pass 2)** — scope the candidate-character pool
  per window so the model only profiles characters that actually
  spoke; tightens grounding and reduces identity-leak failure modes.
- **Translation (later)** — inject voice profiles only for characters
  speaking in the fragment's window. Cuts prompt size dramatically
  for books with large casts and few speakers per scene.

Structure
---------
- ``WindowSpeaker`` — one row per (book, window, character) edge.
  Carries the verbatim phrase Pass 1 used as evidence so we can
  validate the claim and surface it later in review UI.
- ``SpeakerNotepad`` — singleton per book, mirrors ``VoiceNotepad``.
  Carries cross-window scratch notes between Pass 1 windows
  (unresolved speakers, ambiguous attributions).

Why no per-edge status workflow
-------------------------------
Unlike glossary entries or voice profiles, individual (window, character)
speaker edges aren't reviewed by the author one-by-one. If Pass 1
mis-attributes a line, the author resets and re-runs. Authorial review
happens at the voice-profile level (Pass 2 output), not here.

Window alignment
----------------
Pass 1 uses ``VOICE_EXTRACTION_WINDOW_WORDS`` (the same window size as
voice extraction) so ``WindowSpeaker.window_number`` directly indexes
the windows Pass 2 consumes — no alignment math.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
