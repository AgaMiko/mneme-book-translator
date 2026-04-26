"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_language", sa.String(8), nullable=False, server_default="pl"),
        sa.Column("target_language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_books_created_at", "books", ["created_at"])

    op.create_table(
        "chapters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("book_id", "position", name="uq_chapter_position"),
    )
    op.create_index("ix_chapters_book_id", "chapters", ["book_id"])

    op.create_table(
        "paragraphs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chapter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("style", sa.String(64), nullable=True),
        sa.UniqueConstraint("chapter_id", "position", name="uq_paragraph_position"),
    )
    op.create_index("ix_paragraphs_chapter_id", "paragraphs", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_paragraphs_chapter_id", table_name="paragraphs")
    op.drop_table("paragraphs")
    op.drop_index("ix_chapters_book_id", table_name="chapters")
    op.drop_table("chapters")
    op.drop_index("ix_books_created_at", table_name="books")
    op.drop_table("books")
