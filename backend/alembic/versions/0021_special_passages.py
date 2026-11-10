"""special passages (verse, hidden messages, wordplay) and author flags

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "passages_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_table(
        "special_passages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("paragraph_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "dependent_paragraph_ids",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("rule", sa.Text(), server_default="", nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("source_message", sa.Text(), nullable=True),
        sa.Column("target_message", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), server_default="", nullable=False),
        sa.Column("origin", sa.String(length=16), server_default="detected", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="unchecked", nullable=False),
        sa.Column(
            "problems",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("first_translation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checked_translation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_special_passages_book_id", "special_passages", ["book_id"])
    op.create_index("ix_special_passages_chapter_id", "special_passages", ["chapter_id"])
    op.create_table(
        "translation_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("special_passage_id", sa.UUID(), nullable=True),
        sa.Column("paragraph_id", sa.Text(), nullable=True),
        sa.Column("flag_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("author_response", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["special_passage_id"], ["special_passages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_translation_flags_book_id", "translation_flags", ["book_id"])
    op.create_index(
        "ix_translation_flags_special_passage_id", "translation_flags", ["special_passage_id"]
    )


def downgrade() -> None:
    op.drop_table("translation_flags")
    op.drop_table("special_passages")
    op.drop_column("books", "passages_state")
