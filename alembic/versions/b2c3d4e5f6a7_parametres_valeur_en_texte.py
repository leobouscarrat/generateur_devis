"""parametres.valeur en texte

La colonne valeur passe de FLOAT à VARCHAR : certains paramètres ne sont
pas numériques (paliers_quantite = « 1,10,100,1000 », devise = « EUR »).
Le typage est assuré à la lecture par la couche Pydantic, selon la clé.

SQLite ne change pas le type d'une colonne en place : recréation de la
table avec conversion explicite des valeurs existantes en texte.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-09 10:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _remplacer_table(type_valeur: str, conversion: str) -> None:
    """Recrée parametres avec `type_valeur` pour la colonne valeur."""
    op.execute(
        f"""
        CREATE TABLE parametres_nouvelle (
            cle VARCHAR NOT NULL,
            valeur {type_valeur} NOT NULL,
            unite VARCHAR,
            description VARCHAR,
            PRIMARY KEY (cle)
        )
        """
    )
    op.execute(
        "INSERT INTO parametres_nouvelle (cle, valeur, unite, description) "
        f"SELECT cle, {conversion}, unite, description FROM parametres"
    )
    op.execute("DROP TABLE parametres")
    op.execute("ALTER TABLE parametres_nouvelle RENAME TO parametres")


def upgrade() -> None:
    """valeur FLOAT -> VARCHAR (conversion explicite des données)."""
    _remplacer_table("VARCHAR", "CAST(valeur AS TEXT)")


def downgrade() -> None:
    """valeur VARCHAR -> FLOAT (les valeurs non numériques deviennent 0.0)."""
    _remplacer_table("FLOAT", "CAST(valeur AS FLOAT)")
