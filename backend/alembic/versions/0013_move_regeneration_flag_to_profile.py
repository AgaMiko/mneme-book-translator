"""move needs_regeneration from passages to character_voices (if old 0012 ran)

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-17
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    voices_cols = _column_names("character_voices")
    passage_cols = _column_names("voice_selected_passages")

    if "needs_regeneration" not in voices_cols:
        op.add_column(
            "character_voices",
            sa.Column(
                "needs_regeneration",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if "needs_regeneration" in passage_cols:
        op.drop_column("voice_selected_passages", "needs_regeneration")


def downgrade() -> None:
    voices_cols = _column_names("character_voices")
    passage_cols = _column_names("voice_selected_passages")

    if "needs_regeneration" not in passage_cols:
        op.add_column(
            "voice_selected_passages",
            sa.Column(
                "needs_regeneration",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if "needs_regeneration" in voices_cols:
        op.drop_column("character_voices", "needs_regeneration")
