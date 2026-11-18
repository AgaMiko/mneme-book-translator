"""Split character_voices.voice_summary into observation + strategy.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-27

The ORM (``app.models.voice.CharacterVoice``) uses ``source_voice_observation``
and ``target_voice_strategy``. Migrations 0008–0009 still used a single
``voice_summary`` column. This revision aligns the table.

Existing ``voice_summary`` text is copied to ``source_voice_observation``.
``target_voice_strategy`` is initialized to an empty string. Re-run voice
extraction or edit profiles to fill the strategy, per product notes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("character_voices")}

    # Idempotent: already on the new shape (no legacy column).
    if "source_voice_observation" in cols and "voice_summary" not in cols:
        return

    if "source_voice_observation" not in cols:
        op.add_column(
            "character_voices",
            sa.Column("source_voice_observation", sa.Text(), nullable=True),
        )
    if "target_voice_strategy" not in cols:
        op.add_column(
            "character_voices",
            sa.Column("target_voice_strategy", sa.Text(), nullable=True),
        )

    if "voice_summary" in cols:
        op.execute(
            sa.text(
                "UPDATE character_voices SET source_voice_observation = voice_summary, "
                "target_voice_strategy = COALESCE(target_voice_strategy, '')"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE character_voices SET source_voice_observation = "
                "COALESCE(source_voice_observation, ''), "
                "target_voice_strategy = COALESCE(target_voice_strategy, '')"
            )
        )

    op.execute(
        sa.text("ALTER TABLE character_voices ALTER COLUMN source_voice_observation SET NOT NULL")
    )
    op.execute(
        sa.text("ALTER TABLE character_voices ALTER COLUMN target_voice_strategy SET NOT NULL")
    )

    if "voice_summary" in cols:
        op.drop_column("character_voices", "voice_summary")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("character_voices")}

    # Idempotent: already on the old single-column shape.
    if "voice_summary" in cols and "source_voice_observation" not in cols:
        return

    op.add_column(
        "character_voices",
        sa.Column("voice_summary", sa.Text(), nullable=True),
    )
    op.execute(sa.text("UPDATE character_voices SET voice_summary = source_voice_observation"))
    op.execute(sa.text("ALTER TABLE character_voices ALTER COLUMN voice_summary SET NOT NULL"))
    if "source_voice_observation" in cols:
        op.drop_column("character_voices", "source_voice_observation")
    if "target_voice_strategy" in cols:
        op.drop_column("character_voices", "target_voice_strategy")
