"""books.stages_marked_finished: stages the author marked as finished by hand

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "stages_marked_finished",
            postgresql.ARRAY(sa.String(length=16)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("books", "stages_marked_finished")
