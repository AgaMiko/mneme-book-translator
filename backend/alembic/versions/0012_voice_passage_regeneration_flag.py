"""add needs_regeneration flag on character_voices

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-17
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0012"
down_revision: str | None = "a963d457ee71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "character_voices",
        sa.Column(
            "needs_regeneration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("character_voices", "needs_regeneration")
