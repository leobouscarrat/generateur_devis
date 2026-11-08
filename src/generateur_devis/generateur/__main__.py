"""Générer des plans de tôlerie.

Usage :
    uv run python -m generateur_devis.generateur --partie dev --nombre 15
    uv run python -m generateur_devis.generateur --partie test --nombre 50
"""

import argparse

from generateur_devis.generateur import generer_jeu


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--partie", choices=["dev", "test"], default="dev")
    parser.add_argument("--nombre", type=int, default=15)
    args = parser.parse_args()
    dossier = generer_jeu(args.partie, args.nombre)
    print(f"Plans écrits dans {dossier}")


if __name__ == "__main__":
    main()
