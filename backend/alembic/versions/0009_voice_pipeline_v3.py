"""Voice pipeline v3: slim character_voices + candidate/selected tables.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-27

Drops the single reference-passage columns (and dialogue_volume_observed) from
``character_voices``; those live on ``voice_selected_passages`` now. Adds
``voice_passage_candidates`` and ``voice_selected_passages``.

Destructive w.r.t. the dropped column values. Re-run voice extraction after upgrade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS voice_selected_passages"))
    op.execute(sa.text("DROP TABLE IF EXISTS voice_passage_candidates"))

    for col in (
        "reference_passage_source",
        "reference_passage_translation_proposed",
        "reference_passage_translation_authoritative",
        "dialogue_volume_observed",
    ):
        op.execute(sa.text("ALTER TABLE character_voices DROP COLUMN IF EXISTS " + col))

    op.create_table(
        "voice_passage_candidates",
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("why_representative", sa.Text(), nullable=False),
        sa.Column("first_seen_window", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["character_voices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_passage_candidates_voice_id",
        "voice_passage_candidates",
        ["voice_id"],
        unique=False,
    )

    op.create_table(
        "voice_selected_passages",
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("why_selected", sa.Text(), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        sa.Column("translation_proposed", sa.Text(), nullable=True),
        sa.Column("translation_authoritative", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="proposed",
            nullable=False,
        ),
        sa.Column("source_candidate_id", sa.UUID(), nullable=True),
        sa.Column("voice_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_id"],
            ["voice_passage_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["character_voices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_id", "selection_rank", name="uq_voice_selected_passage_rank"),
    )
    op.create_index(
        "ix_voice_selected_passages_voice_id",
        "voice_selected_passages",
        ["voice_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_voice_selected_passages_voice_id", table_name="voice_selected_passages")
    op.drop_table("voice_selected_passages")
    op.drop_index("ix_voice_passage_candidates_voice_id", table_name="voice_passage_candidates")
    op.drop_table("voice_passage_candidates")

    # Recreate 0008-style columns (best-effort; matches old NOT NULL + defaults).
    op.add_column(
        "character_voices",
        sa.Column(
            "reference_passage_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "character_voices",
        sa.Column(
            "reference_passage_translation_proposed",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "character_voices",
        sa.Column("reference_passage_translation_authoritative", sa.Text(), nullable=True),
    )
    op.add_column(
        "character_voices",
        sa.Column(
            "dialogue_volume_observed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
