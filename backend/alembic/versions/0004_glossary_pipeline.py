"""glossary extraction artifacts, working entries, final glossary snapshot

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "glossary_extraction_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_glossary_extraction_runs_book_id",
        "glossary_extraction_runs",
        ["book_id"],
    )

    op.create_table(
        "glossary_window_generations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "extraction_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window_number", sa.Integer(), nullable=False),
        sa.Column("raw_response", JSONB, nullable=False),
        sa.Column("usage_metadata", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "extraction_run_id",
            "window_number",
            name="uq_glossary_window_run_number",
        ),
    )
    op.create_index(
        "ix_glossary_window_generations_run_id",
        "glossary_window_generations",
        ["extraction_run_id"],
    )

    op.create_table(
        "glossary_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_form", sa.String(length=200), nullable=False),
        sa.Column("term_type", sa.String(length=32), nullable=False),
        sa.Column("meaning", sa.Text(), nullable=False),
        sa.Column("translation_recommendation", JSONB, nullable=False),
        sa.Column(
            "variants",
            sa.ARRAY(sa.String(length=200)),
            nullable=False,
            server_default=sa.text("'{}'::varchar(200)[]"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("first_seen_window", sa.Integer(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "extraction_run_id",
            "canonical_form",
            name="uq_glossary_run_canonical",
        ),
    )
    op.create_index("ix_glossary_entries_book_id", "glossary_entries", ["book_id"])
    op.create_index(
        "ix_glossary_entries_extraction_run_id",
        "glossary_entries",
        ["extraction_run_id"],
    )

    op.create_table(
        "glossary_notepads",
        sa.Column(
            "extraction_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("glossary_extraction_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "notes",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_window_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "final_glossaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_extraction_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("glossary_extraction_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("label", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_final_glossaries_book_id", "final_glossaries", ["book_id"])

    op.create_table(
        "final_glossary_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "final_glossary_id",
            UUID(as_uuid=True),
            sa.ForeignKey("final_glossaries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_glossary_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("glossary_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("canonical_form", sa.String(length=200), nullable=False),
        sa.Column("term_type", sa.String(length=32), nullable=False),
        sa.Column("meaning", sa.Text(), nullable=False),
        sa.Column(
            "variants",
            sa.ARRAY(sa.String(length=200)),
            nullable=False,
            server_default=sa.text("'{}'::varchar(200)[]"),
        ),
        sa.Column("translation", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "final_glossary_id",
            "canonical_form",
            name="uq_final_glossary_canonical",
        ),
    )
    op.create_index(
        "ix_final_glossary_entries_final_glossary_id",
        "final_glossary_entries",
        ["final_glossary_id"],
    )

    op.add_column(
        "books",
        sa.Column(
            "active_final_glossary_id",
            UUID(as_uuid=True),
            sa.ForeignKey("final_glossaries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("books", "active_final_glossary_id")
    op.drop_table("final_glossary_entries")
    op.drop_table("final_glossaries")
    op.drop_table("glossary_notepads")
    op.drop_table("glossary_entries")
    op.drop_table("glossary_window_generations")
    op.drop_table("glossary_extraction_runs")
