"""speakers identification stage: window_speakers, speaker_notepads, book columns

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-16

Adds the persistence layer for Pass 1 (speaker identification), the new
stage that runs before voice extraction. Pass 1 records, per manuscript
window, which glossary characters have at least one quoted speaking
line.

Voice extraction internals are NOT touched by this migration. The new
table is consumed downstream (by voice extraction in a later step, and
by translation later still); this revision is purely additive.

Window alignment with voice extraction is by convention — Pass 1 uses
``VOICE_EXTRACTION_WINDOW_WORDS``, so ``window_speakers.window_number``
directly indexes the voice-extraction windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "window_speakers",
        sa.Column("window_number", sa.Integer(), nullable=False),
        sa.Column("quoted_evidence", sa.Text(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("glossary_entry_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["glossary_entry_id"], ["glossary_entries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "book_id",
            "window_number",
            "glossary_entry_id",
            name="uq_window_speaker_triple",
        ),
    )
    op.create_index(
        "ix_window_speakers_book_window",
        "window_speakers",
        ["book_id", "window_number"],
        unique=False,
    )
    op.create_index(
        "ix_window_speakers_book_character",
        "window_speakers",
        ["book_id", "glossary_entry_id"],
        unique=False,
    )

    op.create_table(
        "speaker_notepads",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "last_window_number", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id"),
    )

    op.add_column(
        "books",
        sa.Column(
            "speakers_extraction_status",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "speakers_extraction_cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "speakers_extraction_windows_total", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "books",
        sa.Column(
            "speakers_extraction_windows_completed", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "books",
        sa.Column("speakers_extraction_last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("books", "speakers_extraction_last_error")
    op.drop_column("books", "speakers_extraction_windows_completed")
    op.drop_column("books", "speakers_extraction_windows_total")
    op.drop_column("books", "speakers_extraction_cancel_requested")
    op.drop_column("books", "speakers_extraction_status")

    op.drop_table("speaker_notepads")

    op.drop_index(
        "ix_window_speakers_book_character", table_name="window_speakers"
    )
    op.drop_index("ix_window_speakers_book_window", table_name="window_speakers")
    op.drop_table("window_speakers")
