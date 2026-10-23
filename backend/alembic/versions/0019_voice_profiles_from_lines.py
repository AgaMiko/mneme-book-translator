"""voice profiles built from dialogue lines: evidence, line count, passage range

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "character_voices",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "character_voices",
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "character_voices",
        sa.Column("low_evidence", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for col in ("first_paragraph_id", "last_paragraph_id"):
        op.add_column(
            "voice_selected_passages",
            sa.Column(
                col,
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("paragraphs.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("voice_selected_passages", "last_paragraph_id")
    op.drop_column("voice_selected_passages", "first_paragraph_id")
    op.drop_column("character_voices", "low_evidence")
    op.drop_column("character_voices", "line_count")
    op.drop_column("character_voices", "evidence")
