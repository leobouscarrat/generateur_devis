"""Générer des plans de tôlerie.

Usage :
    uv run python -m generateur_devis.generateur --partie dev --nombre 15
    uv run python -m generateur_devis.generateur --partie test --nombre 50
    uv run python -m generateur_devis.generateur --partie dev --nombre 8 --erreurs
"""

import argparse

from generateur_devis.generateur import generer_jeu, generer_jeu_erreurs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--partie", choices=["dev", "test"], default="dev")
    parser.add_argument("--nombre", type=int, default=15)
    parser.add_argument(
        "--erreurs", action="store_true", help="Plans volontairement erronés (niveau E)"
    )
    args = parser.parse_args()
    generer = generer_jeu_erreurs if args.erreurs else generer_jeu
    dossier = generer(args.partie, args.nombre)
    print(f"Plans écrits dans {dossier}")


if __name__ == "__main__":
    main()
