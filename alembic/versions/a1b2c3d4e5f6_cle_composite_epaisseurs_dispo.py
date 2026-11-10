"""cle composite sur epaisseurs_dispo

La clé primaire passe de (matiere_id) à (matiere_id, epaisseur_mm) :
le doc (docs/sources_donnees.md §2.2) prévoit une ligne par couple
matière × épaisseur, ce que la clé simple interdisait.

SQLite ne sait pas modifier une clé primaire en place, et la PK
d'origine est anonyme (pas de convention de nommage sur Base.metadata)
: on recrée la table en SQL explicite, avec copie des données.

Revision ID: a1b2c3d4e5f6
Revises: 7cb34be7f89d
Create Date: 2026-11-09 09:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '7cb34be7f89d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLONNES = "matiere_id, epaisseur_mm, format_mm, surcout_pct, en_stock"


def _remplacer_table(pk: str) -> None:
    """Recrée epaisseurs_dispo avec la clé primaire `pk`, en copiant les données."""
    op.execute(
        f"""
        CREATE TABLE epaisseurs_dispo_nouvelle (
            matiere_id VARCHAR NOT NULL,
            epaisseur_mm FLOAT NOT NULL,
            format_mm VARCHAR,
            surcout_pct FLOAT NOT NULL,
            en_stock BOOLEAN NOT NULL,
            PRIMARY KEY ({pk}),
            FOREIGN KEY(matiere_id) REFERENCES matieres (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        f"INSERT INTO epaisseurs_dispo_nouvelle ({_COLONNES}) "
        f"SELECT {_COLONNES} FROM epaisseurs_dispo"
    )
    op.execute("DROP TABLE epaisseurs_dispo")
    op.execute("ALTER TABLE epaisseurs_dispo_nouvelle RENAME TO epaisseurs_dispo")


def upgrade() -> None:
    """PK composite (matiere_id, epaisseur_mm)."""
    _remplacer_table("matiere_id, epaisseur_mm")


def downgrade() -> None:
    """Retour à la PK simple (matiere_id)."""
    _remplacer_table("matiere_id")
