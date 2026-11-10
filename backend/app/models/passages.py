"""ORM models for special passages and author flags (Step 6).

- ``SpecialPassage`` — a run of paragraphs inside one chapter that follows
  a rule normal translation breaks: verse or a song (lines, rhyme), a
  hidden message (letters that spell something), or wordplay the plot
  depends on. Found by a scan of the manuscript or marked by the author.
  After translation each passage is checked; when the English breaks the
  rule it is translated again and the new text replaces the old one in the
  fragment's final rendition. ``first_translation`` keeps the text from
  before, so the author can restore it.
- ``TranslationFlag`` — one item for the author to look at. For now every
  flag belongs to a special passage; translator notes can move here later.

Paragraph ids are stored as text, because a chapter heading (which can hold
an epigraph in verse) uses the pseudo id ``title:<chapter id>``.

See ``docs/step6-special-passages.md``.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy resolves Mapped[] at runtime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

PASSAGE_KINDS: tuple[str, ...] = ("verse", "hidden_message", "wordplay")


class SpecialPassage(Base):
    __tablename__ = "special_passages"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    # Order in the book: chapter position * 100000 + first paragraph position.
    position: Mapped[int] = mapped_column(Integer)
    # verse | hidden_message | wordplay
    kind: Mapped[str] = mapped_column(String(24))
    paragraph_ids: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Paragraphs of the same chapter that quote the passage or state what it hides.
    dependent_paragraph_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default_factory=list, server_default="{}"
    )
    # The rule in plain words, for the author and for the prompts. Empty on a
    # passage the author marked until the first check works it out.
    rule: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Hidden messages: which units carry the letters (see ``passage_rules.Unit``),
    # what the source spells, and what the English should spell.
    unit: Mapped[str | None] = mapped_column(String(16), default=None)
    source_message: Mapped[str | None] = mapped_column(Text, default=None)
    target_message: Mapped[str | None] = mapped_column(Text, default=None)
    evidence: Mapped[str] = mapped_column(Text, default="", server_default="")
    # detected | author
    origin: Mapped[str] = mapped_column(String(16), default="detected", server_default="detected")
    # unchecked | passed | corrected | failed | author | dismissed
    #   passed    — the normal translation keeps the rule
    #   corrected — it did not; a checked new translation replaced it
    #   failed    — it did not, and no new translation passed the check
    #   author    — the author chose or wrote the text
    #   dismissed — the author said this is not a special passage
    status: Mapped[str] = mapped_column(String(16), default="unchecked", server_default="unchecked")
    # What the last check found: ["…", "…"]; empty when the rule is kept.
    problems: Mapped[list[str]] = mapped_column(JSONB, default_factory=list, server_default="[]")
    # [{"paragraph_id", "text"}] for the passage and its dependent paragraphs:
    # the English before the first correction, and the English at the last
    # check or author action (to notice a later re-translation).
    first_translation: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    checked_translation: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=None)
    # Every new translation tried:
    # [{"paragraphs": [...], "target_message", "notes", "problems": [...]}]
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default_factory=list, server_default="[]"
    )

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), init=False
    )


class TranslationFlag(Base):
    __tablename__ = "translation_flags"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    special_passage_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("special_passages.id", ondelete="CASCADE"),
        index=True,
        default=None,
    )
    paragraph_id: Mapped[str | None] = mapped_column(Text, default=None)
    # special_passage (more kinds when translator notes move here)
    flag_type: Mapped[str] = mapped_column(String(32), default="special_passage")
    # blocking | review | fyi
    severity: Mapped[str] = mapped_column(String(16), default="review")
    question: Mapped[str] = mapped_column(Text, default="")
    # open | accepted | changed | dismissed
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    author_response: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )
