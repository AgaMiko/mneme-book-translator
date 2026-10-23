"""dialogue_lines: every dialogue paragraph with its speaker and addressee

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dialogue_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paragraph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paragraphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("chunk_number", sa.Integer(), nullable=False),
        sa.Column("word_offset", sa.Integer(), nullable=False),
        sa.Column("marker", sa.String(16), nullable=False),
        sa.Column("speech_text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "speaker_glossary_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("glossary_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "addressee_glossary_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("glossary_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("mixed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id", "paragraph_id", name="uq_dialogue_line_paragraph"),
    )
    op.create_index("ix_dialogue_lines_book_line", "dialogue_lines", ["book_id", "line_index"])
    op.create_index(
        "ix_dialogue_lines_book_speaker",
        "dialogue_lines",
        ["book_id", "speaker_glossary_entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dialogue_lines_book_speaker", table_name="dialogue_lines")
    op.drop_index("ix_dialogue_lines_book_line", table_name="dialogue_lines")
    op.drop_table("dialogue_lines")
