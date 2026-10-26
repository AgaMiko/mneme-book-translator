"""cast pass: short translation brief per voice, review of passage translations

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-26
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("character_voices", sa.Column("translation_brief", sa.Text(), nullable=True))
    op.add_column(
        "voice_selected_passages", sa.Column("translation_review", sa.Text(), nullable=True)
    )
    op.add_column(
        "voice_selected_passages", sa.Column("translation_revised", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("voice_selected_passages", "translation_revised")
    op.drop_column("voice_selected_passages", "translation_review")
    op.drop_column("character_voices", "translation_brief")
