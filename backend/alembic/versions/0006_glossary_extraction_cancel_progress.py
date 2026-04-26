"""glossary extraction cancel flag and window progress columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "glossary_extraction_cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "books",
        sa.Column("glossary_extraction_windows_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "books",
        sa.Column("glossary_extraction_windows_completed", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("books", "glossary_extraction_windows_completed")
    op.drop_column("books", "glossary_extraction_windows_total")
    op.drop_column("books", "glossary_extraction_cancel_requested")
