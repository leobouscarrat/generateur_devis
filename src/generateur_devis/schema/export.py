"""Export du format de la pièce en JSON Schema.

Le fichier exporté sert à imposer le format de réponse aux modèles, et à relire le format
sans lire le code Python.

Usage : uv run python -m generateur_devis.schema.export
"""

import json
from pathlib import Path

from generateur_devis.schema.piece import PieceExtraite

CHEMIN_SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "piece_extraite.schema.json"


def json_schema() -> dict:
    return PieceExtraite.model_json_schema()


def texte_schema() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    CHEMIN_SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    CHEMIN_SCHEMA.write_text(texte_schema(), encoding="utf-8")
    print(f"Schéma écrit dans {CHEMIN_SCHEMA}")


if __name__ == "__main__":
    main()
