"""fragment translation: fragments, runs, run fragments, renditions

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21

First slice of Step 5 (see docs/step5-translation-pipeline.md). Purely
additive: four new tables, no changes to existing ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "translation_fragments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "book_id", _uuid(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "chapter_id",
            _uuid(),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("paragraph_ids", postgresql.ARRAY(_uuid()), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("start_word_offset", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("book_id", "position", name="uq_translation_fragment_position"),
    )
    op.create_index("ix_translation_fragments_book_id", "translation_fragments", ["book_id"])
    op.create_index("ix_translation_fragments_chapter_id", "translation_fragments", ["chapter_id"])

    op.create_table(
        "translation_runs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "book_id", _uuid(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("chapter_ids", postgresql.ARRAY(_uuid()), nullable=True),
        sa.Column("fragments_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fragments_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fragments_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "models",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_translation_runs_book_id", "translation_runs", ["book_id"])

    op.create_table(
        "translation_run_fragments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("translation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fragment_id",
            _uuid(),
            sa.ForeignKey("translation_fragments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("last_stage", sa.String(16), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "fragment_id", name="uq_translation_run_fragment"),
    )
    op.create_index("ix_translation_run_fragments_run_id", "translation_run_fragments", ["run_id"])
    op.create_index(
        "ix_translation_run_fragments_fragment_id",
        "translation_run_fragments",
        ["fragment_id"],
    )

    op.create_table(
        "fragment_renditions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "run_id",
            _uuid(),
            sa.ForeignKey("translation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fragment_id",
            _uuid(),
            sa.ForeignKey("translation_fragments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("paragraphs", postgresql.JSONB(), nullable=False),
        sa.Column(
            "notes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("usage_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "fragment_id", "stage", name="uq_fragment_rendition_stage"),
    )
    op.create_index("ix_fragment_renditions_run_id", "fragment_renditions", ["run_id"])
    op.create_index("ix_fragment_renditions_fragment_id", "fragment_renditions", ["fragment_id"])


def downgrade() -> None:
    op.drop_table("fragment_renditions")
    op.drop_table("translation_run_fragments")
    op.drop_table("translation_runs")
    op.drop_table("translation_fragments")
