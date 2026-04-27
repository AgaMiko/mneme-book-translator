"""ORM models for persisted character voice profiles.

The persisted shape — what survives across passes, gets reviewed by the
author, and is consumed by translation. Distinct from:

- ``app.generation.prompt_manager.models.extract_voices_model`` — the
  LLM contract. Service code converts.
- ``app.schemas.voice`` — the API contract for the FE review UI.

Tables
------
- ``character_voices``  — one row per character profile. Contains the
  voice_summary (free-text prose) and a reference passage stored as
  three fields (source / proposed translation / authoritative
  translation).
- ``voice_notepads``    — one row per book. Working memory between
  voice-extraction passes; fully replaced each pass.

There is **no longer** a ``voice_contexts`` table. The previous schema
captured situational shifts as structured rows; the new schema folds
that observation into the prose voice_summary instead — the model
writes a single description that includes any contextual shifts. Three
reasons:

1. The model was bad at *clustering* shifts ("mentoring Mira" appeared
   three times across windows as nominally separate contexts);
   structured contexts forced human consolidation work that prose
   doesn't.
2. Translation can't actually match scene labels to fragment context
   reliably enough to use structured contexts during translation.
3. A flat prose summary is what translation prompts will quote
   directly, with no stitching needed.

The reference passage replaces the old ``dialogue_excerpts`` JSONB
array. Where excerpts were a *collection* of representative quotes the
author had to curate, the reference passage is a *single*
quote-plus-translation pair: 3-4 sentences the model picks, the model
translates, and the author reviews. One pair per character; no
curation work beyond accept/edit/reject.

Status workflow
---------------
``proposed | accepted | adjusted | rejected``

- ``proposed``  — extraction wrote it; not reviewed.
- ``accepted``  — author accepted both summary and reference translation
                  unchanged. ``reference_passage_translation_authoritative``
                  is set equal to the proposed translation.
- ``adjusted``  — author edited the summary, the reference translation,
                  or both. ``authoritative`` carries the edit; the
                  proposed remains for restoration.
- ``rejected``  — author dismissed the profile. Translation skips it
                  and falls back to no profile context for that
                  character. ``authoritative`` stays NULL.

The LLM never sees status. It's FE/BE territory.

Why the dual-field translation but not dual-field summary
---------------------------------------------------------
The reference translation is the artifact the author most concretely
evaluates ("does this English Borys sound right?"), and edits to it
are the strongest feedback signal we collect. Preserving the model's
original alongside the author's edited version lets us:

- Restore the model output if the author wants to revert their edits.
- Track translation quality over time (compare proposed vs.
  authoritative across many books).
- Surface diffs in future review screens without needing version
  history infrastructure.

The voice_summary doesn't carry the same evaluation weight — author
edits to it are usually small refinements, not wholesale corrections —
so a single ``voice_summary`` field with edits-in-place is fine. If
later analysis shows summary edits need preservation too, a second
field can be added in a tiny migration.

Precondition
------------
Voice extraction depends on completed glossary extraction. The
``glossary_entry_id`` foreign key carries this dependency at the
database level.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class CharacterVoice(Base):
    __tablename__ = "character_voices"
    __table_args__ = (
        # One profile per glossary entry. Two rows for the same
        # character would mean voice has been duplicated — an error
        # state worth catching at the DB level.
        UniqueConstraint(
            "glossary_entry_id",
            name="uq_voice_glossary_entry",
        ),
    )

    # The full voice description as prose. Replaces the previous
    # register / diction / verbal_tics / address_conventions /
    # in_their_own_words / speech_acts / contexts breakdown — all of
    # those collapse into this single Text field. The model writes
    # 2-3 sentences; the author edits in place if needed.
    voice_summary: Mapped[str] = mapped_column(Text)

    # Reference passage — a single source/translation pair per
    # character, picked and translated by the model. Three fields:
    #
    # source              : the Polish (or other source-language)
    #                       passage. Never edited; the source text is
    #                       authoritative.
    # translation_proposed: the model's first translation. Preserved
    #                       through any author edits; useful for
    #                       restoration and for tracking model quality.
    # translation_authoritative: NULL until the author reviews. Set
    #                       equal to translation_proposed on accept,
    #                       set to the edited text on adjust, stays
    #                       NULL on reject. Translation downstream
    #                       reads this field; if NULL, no calibration
    #                       sample is available.
    reference_passage_source: Mapped[str] = mapped_column(Text)
    reference_passage_translation_proposed: Mapped[str] = mapped_column(Text)
    reference_passage_translation_authoritative: Mapped[str | None] = mapped_column(
        Text, default=None
    )

    # Workflow status — not in any LLM schema.
    status: Mapped[str] = mapped_column(
        String(16), default="proposed", server_default="proposed"
    )

    # Provenance: counts dialogue lines/turns the model has seen for
    # this character, accumulated code-side as windows process. Replaces
    # the discarded ``confidence`` field — this is the honest signal of
    # how much evidence backs a profile.
    dialogue_volume_observed: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_window: Mapped[int] = mapped_column(Integer)
    last_observed_window: Mapped[int] = mapped_column(Integer)

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


class VoiceNotepad(Base):
    """The voice-extraction notepad as it stood at the end of the last pass.

    One row per book. Fully replaced each pass — the model writes
    whatever single note it judges worth carrying forward (cap=1).
    Stored rather than recomputed because the next pass needs the
    previous note verbatim, including its category label.
    """

    __tablename__ = "voice_notepads"

    book_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
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
