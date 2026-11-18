"""add metadata_status to books

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25

Existing rows are backfilled with ``"ready"`` because they were uploaded
under the previous synchronous-metadata flow and either already have
metadata populated or never will. New rows default to ``"pending"`` and
are flipped by the background enrichment task.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "metadata_status",
            sa.String(16),
            nullable=False,
            server_default="ready",
        ),
    )


def downgrade() -> None:
    op.drop_column("books", "metadata_status")
