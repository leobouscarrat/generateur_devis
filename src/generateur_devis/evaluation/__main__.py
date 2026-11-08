"""Lancer une évaluation.

Usage :
    uv run python -m generateur_devis.evaluation --jeu ecado --partie dev --modele claude-code:sonnet
    uv run python -m generateur_devis.evaluation --jeu cadsy --partie test --limite 10

Jeux : cadsy, ecado, prive (plans annotés à la main dans data/prive/), tolerie (plans générés).
"""

import argparse
import sys

from generateur_devis.evaluation.executer import executer, tableau
from generateur_devis.evaluation.jeux import charger_jeu
from generateur_devis.llm import creer_modele


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--jeu", required=True, choices=["cadsy", "ecado", "prive", "tolerie"])
    parser.add_argument("--partie", default="dev", choices=["dev", "test"])
    parser.add_argument("--modele", default="claude-code:sonnet")
    parser.add_argument("--limite", type=int, help="Ne traiter que les N premiers plans")
    parser.add_argument("--paralleles", type=int, default=2, help="Appels simultanés")
    args = parser.parse_args()

    jeu = charger_jeu(args.jeu, args.partie)
    if args.limite:
        jeu.echantillons = jeu.echantillons[: args.limite]
    print(f"{len(jeu.echantillons)} plans à évaluer…", file=sys.stderr)

    resultats, resume, chemin = executer(
        jeu, creer_modele(args.modele), args.partie, args.paralleles
    )
    for r in resultats:
        if r.extraction.piece is None:
            print(f"Échec {r.identifiant} : {r.extraction.erreur}", file=sys.stderr)
    print(tableau(resume))
    print(f"\nDétail : {chemin}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
