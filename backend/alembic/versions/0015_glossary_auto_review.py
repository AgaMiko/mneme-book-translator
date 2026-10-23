"""glossary auto review: who decided a term, and undoable merges

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "glossary_entries",
        sa.Column("auto_review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "glossary_entries",
        sa.Column(
            "merged_into_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("glossary_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("glossary_entries", "merged_into_id")
    op.drop_column("glossary_entries", "auto_review")
