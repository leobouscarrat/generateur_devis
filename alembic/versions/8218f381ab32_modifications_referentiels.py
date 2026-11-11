"""modifications_referentiels

Revision ID: 8218f381ab32
Revises: b2c3d4e5f6a7
Create Date: 2026-11-11 18:23:37.512861

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8218f381ab32"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Audit des modifications de référentiels (§12 : daté et attribué)."""
    op.create_table(
        "modifications_referentiels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_nom", sa.String(), nullable=False),
        sa.Column("ligne_id", sa.String(), nullable=False),
        sa.Column("champ", sa.String(), nullable=False),
        sa.Column("valeur_avant", sa.String(), nullable=True),
        sa.Column("valeur_apres", sa.String(), nullable=True),
        sa.Column("auteur", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("modifications_referentiels")
