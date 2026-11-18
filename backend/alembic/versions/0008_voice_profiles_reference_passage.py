"""Replace character_voices + voice_contexts with reference-passage schema.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-27

The ORM (``app.models.voice.CharacterVoice``) expects voice_summary and
reference passage fields. Migration 0007 created the older slot-based
schema; this revision drops the obsolete table and context child table
and recreates ``character_voices`` to match the current model.

Destructive: existing voice rows are dropped. Glossary and other book
data are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Order: child (voice_contexts) then parent (character_voices).
    op.execute(sa.text("DROP TABLE IF EXISTS voice_contexts"))
    op.execute(sa.text("DROP TABLE IF EXISTS character_voices"))

    op.create_table(
        "character_voices",
        sa.Column("voice_summary", sa.Text(), nullable=False),
        sa.Column("reference_passage_source", sa.Text(), nullable=False),
        sa.Column("reference_passage_translation_proposed", sa.Text(), nullable=False),
        sa.Column("reference_passage_translation_authoritative", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="proposed", nullable=False),
        sa.Column(
            "dialogue_volume_observed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("first_seen_window", sa.Integer(), nullable=False),
        sa.Column("last_observed_window", sa.Integer(), nullable=False),
        sa.Column("glossary_entry_id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["glossary_entry_id"], ["glossary_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("glossary_entry_id", name="uq_voice_glossary_entry"),
    )
    op.create_index("ix_character_voices_book_id", "character_voices", ["book_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_character_voices_book_id", table_name="character_voices")
    op.drop_table("character_voices")

    op.create_table(
        "character_voices",
        sa.Column("register", sa.String(length=200), nullable=False),
        sa.Column("diction", sa.Text(), nullable=False),
        sa.Column("speech_acts", sa.String(length=32), nullable=False),
        sa.Column(
            "verbal_tics",
            postgresql.ARRAY(sa.String(length=120)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("address_conventions", sa.Text(), nullable=False),
        sa.Column("in_their_own_words", sa.Text(), nullable=False),
        sa.Column(
            "dialogue_excerpts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(length=16), server_default="proposed", nullable=False),
        sa.Column("dialogue_volume_observed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_window", sa.Integer(), nullable=False),
        sa.Column("last_observed_window", sa.Integer(), nullable=False),
        sa.Column("glossary_entry_id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["glossary_entry_id"], ["glossary_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("glossary_entry_id", name="uq_voice_glossary_entry"),
    )
    op.create_index("ix_character_voices_book_id", "character_voices", ["book_id"], unique=False)

    op.create_table(
        "voice_contexts",
        sa.Column("context", sa.String(length=120), nullable=False),
        sa.Column("register", sa.String(length=200), nullable=False),
        sa.Column("diction", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="proposed", nullable=False),
        sa.Column("voice_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["voice_id"], ["character_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_contexts_voice_id", "voice_contexts", ["voice_id"], unique=False)
