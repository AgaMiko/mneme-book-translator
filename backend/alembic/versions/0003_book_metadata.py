"""add book metadata fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-25

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("author", sa.String(length=500), nullable=True))
    op.add_column(
        "books", sa.Column("manuscript_language", sa.String(length=64), nullable=True)
    )
    op.add_column("books", sa.Column("language_style_note", sa.Text(), nullable=True))
    op.add_column("books", sa.Column("metadata_model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "metadata_model")
    op.drop_column("books", "language_style_note")
    op.drop_column("books", "manuscript_language")
    op.drop_column("books", "author")

