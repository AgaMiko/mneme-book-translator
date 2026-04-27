"""character voices, contexts, notepad + book voice extraction lifecycle

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["voice_id"], ["character_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_contexts_voice_id", "voice_contexts", ["voice_id"], unique=False)

    op.create_table(
        "voice_notepads",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("last_window_number", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id"),
    )

    op.add_column(
        "books",
        sa.Column(
            "voice_extraction_status",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "voice_extraction_cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "books",
        sa.Column("voice_extraction_windows_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "books",
        sa.Column("voice_extraction_windows_completed", sa.Integer(), nullable=True),
    )
    op.add_column(
        "books",
        sa.Column("voice_extraction_last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("books", "voice_extraction_last_error")
    op.drop_column("books", "voice_extraction_windows_completed")
    op.drop_column("books", "voice_extraction_windows_total")
    op.drop_column("books", "voice_extraction_cancel_requested")
    op.drop_column("books", "voice_extraction_status")
    op.drop_table("voice_notepads")
    op.drop_index("ix_voice_contexts_voice_id", table_name="voice_contexts")
    op.drop_table("voice_contexts")
    op.drop_index("ix_character_voices_book_id", table_name="character_voices")
    op.drop_table("character_voices")
