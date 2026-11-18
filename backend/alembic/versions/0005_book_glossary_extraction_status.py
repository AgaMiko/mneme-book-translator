"""add book glossary_extraction_status for async extraction polling

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "books",
        sa.Column(
            "glossary_extraction_status",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
    )


def downgrade() -> None:
    op.drop_column("books", "glossary_extraction_status")
