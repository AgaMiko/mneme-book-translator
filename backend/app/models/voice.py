"""ORM models for persisted character voices, candidate passages, and
selected reference passages.

This is the fourth schema revision. The single ``voice_summary`` field
is split into two:

- ``source_voice_observation`` — what the character is REALLY doing
  in the source language. Names specific linguistic markers.
- ``target_voice_strategy`` — how to render that voice in the target
  language. Names specific markers and avoidances.

Why split
---------
Voice work is two cognitive jobs: observe what the source is doing,
then decide how the target should render it. Conflating them into one
field forced the model to do both at once and produced vague results
("rural feel") that didn't give the translator anything specific to
work with. Splitting makes each job nameable, reviewable independently,
and editable by the author without disturbing the other.

The author's edit on these fields is where model approximation becomes
authorial intent. Translation runs after voice review, with both
fields in context — strategy is the primary directive, observation
provides supporting context.

Status workflows (unchanged)
----------------------------
Profile status (``character_voices.status``):
  ``proposed | accepted | adjusted | rejected``

Selected-passage status (``voice_selected_passages.status``):
  Same four-state workflow, applied per-passage.

Precondition (unchanged)
------------------------
Voice extraction depends on completed glossary extraction. The
``glossary_entry_id`` foreign key carries this dependency at the
database level.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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


class CharacterVoice(Base):
    """One voice profile per character (i.e., per glossary character entry).

    Carries two voice fields and provenance metadata. Reference
    passages are in a separate table.
    """

    __tablename__ = "character_voices"
    __table_args__ = (
        UniqueConstraint(
            "glossary_entry_id",
            name="uq_voice_glossary_entry",
        ),
    )

    # The two voice fields. Both are written in the target language.
    # Observation describes source-language features; strategy directs
    # target-language rendering.
    source_voice_observation: Mapped[str] = mapped_column(Text)
    target_voice_strategy: Mapped[str] = mapped_column(Text)

    # Provenance — windows where this profile was active.
    first_seen_window: Mapped[int] = mapped_column(Integer)
    last_observed_window: Mapped[int] = mapped_column(Integer)

    # Workflow status — not in any LLM schema.
    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")

    # Author flagged the whole profile for a targeted re-extraction pass.
    needs_regeneration: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
    )

    # Built from all of the character's lines (voice redesign): the features
    # and register shifts with the dialogue_lines paragraph ids that show
    # them, how many speech lines the profile saw, and whether that was too
    # few to say much.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default_factory=dict, server_default="{}"
    )
    line_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    low_evidence: Mapped[bool] = mapped_column(default=False, server_default="false")

    # Short rules for the translator, written by the cast pass with the whole
    # cast in view. Translation sends this instead of observation + strategy
    # when it is set.
    translation_brief: Mapped[str | None] = mapped_column(Text, default=None)

    # Foreign keys and relationships
    glossary_entry_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("glossary_entries.id", ondelete="CASCADE"),
        init=False,
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )

    book: Mapped["Book"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Book",
        back_populates="character_voices",
        init=False,
    )
    glossary_entry: Mapped["GlossaryEntry"] = relationship(  # type: ignore[name-defined] # noqa: F821
        init=False,
    )
    candidates: Mapped[list["VoicePassageCandidate"]] = relationship(
        back_populates="voice",
        cascade="all, delete-orphan",
        init=False,
    )
    selected_passages: Mapped[list["VoiceSelectedPassage"]] = relationship(
        back_populates="voice",
        cascade="all, delete-orphan",
        init=False,
    )


class VoicePassageCandidate(Base):
    """A candidate passage flagged during voice extraction.

    Pooled with other candidates for the same voice; selection chain
    later picks 1-4 of these as the final reference passages. Cap of 8
    per voice is enforced by service code.

    Candidates that don't get selected stay in the table for
    traceability — useful for debugging and for future selection
    re-runs if percentile thresholds change.
    """

    __tablename__ = "voice_passage_candidates"

    source_text: Mapped[str] = mapped_column(Text)
    why_representative: Mapped[str] = mapped_column(Text)
    first_seen_window: Mapped[int] = mapped_column(Integer)

    voice_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("character_voices.id", ondelete="CASCADE"),
        init=False,
    )
    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4, init=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), init=False
    )

    voice: Mapped[CharacterVoice] = relationship(back_populates="candidates", init=False)


class VoiceSelectedPassage(Base):
    """A passage chosen by the selection chain as a final reference.

    Each voice gets 1-4 of these, depending on the percentile bucket
    its character lands in (computed from glossary occurrence_count).
    """

    __tablename__ = "voice_selected_passages"
    __table_args__ = (
        UniqueConstraint(
            "voice_id",
            "selection_rank",
            name="uq_voice_selected_passage_rank",
        ),
    )

    source_text: Mapped[str] = mapped_column(Text)
    why_selected: Mapped[str] = mapped_column(Text)
    selection_rank: Mapped[int] = mapped_column(Integer)

    translation_proposed: Mapped[str | None] = mapped_column(Text, default=None)
    translation_authoritative: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")

    source_candidate_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("voice_passage_candidates.id", ondelete="SET NULL"),
        default=None,
    )
    # Cast pass: why the proposed English flattens this voice or sounds like
    # another character, and a revision to consider. Empty when it reads right.
    translation_review: Mapped[str | None] = mapped_column(Text, default=None)
    translation_revised: Mapped[str | None] = mapped_column(Text, default=None)

    # Paragraph range the passage was cut from (profiles built from lines).
    first_paragraph_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("paragraphs.id", ondelete="SET NULL"),
        default=None,
    )
    last_paragraph_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("paragraphs.id", ondelete="SET NULL"),
        default=None,
    )

    voice_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("character_voices.id", ondelete="CASCADE"),
        init=False,
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

    voice: Mapped[CharacterVoice] = relationship(back_populates="selected_passages", init=False)


class VoiceNotepad(Base):
    """Voice-extraction notepad as it stood at the end of the last pass."""

    __tablename__ = "voice_notepads"

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
