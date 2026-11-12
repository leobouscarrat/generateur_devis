"""Lancer une évaluation.

Usage :
    uv run python -m etude_extraction --jeu ecado --partie dev --modele claude-code:sonnet
    uv run python -m etude_extraction --jeu cadsy --partie test --limite 10
    uv run python -m etude_extraction --jeu tolerie --niveau 3   # photos
    uv run python -m etude_extraction --jeu tolerie_erreurs      # plans erronés

Jeux : cadsy, ecado, prive (plans annotés à la main dans data/prive/), tolerie (plans générés),
tolerie_erreurs (plans générés volontairement erronés),
tolerie_incoherences (plans générés avec une information invraisemblable).
Niveaux (jeux tolerie) : 0 PDF propre, 1 image propre, 2 scan, 3 photo.
"""

import argparse
import sys

from etude_extraction.executer import executer, tableau
from etude_extraction.jeux import charger_jeu
from generateur_devis.llm import ErreurModele, argument_modele, creer_modele


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--jeu",
        required=True,
        choices=["cadsy", "ecado", "prive", "tolerie", "tolerie_erreurs", "tolerie_incoherences"],
    )
    parser.add_argument("--partie", default="dev", choices=["dev", "test"])
    parser.add_argument("--niveau", type=int, default=0, choices=[0, 1, 2, 3])
    parser.add_argument("--modele", type=argument_modele, default="claude-code:sonnet")
    parser.add_argument("--limite", type=int, help="Ne traiter que les N premiers plans")
    parser.add_argument("--paralleles", type=int, default=2, help="Appels simultanés")
    args = parser.parse_args()

    # Modèle construit avant le jeu : une configuration invalide échoue tout de
    # suite, avec un message clair (issue #99).
    try:
        modele = creer_modele(args.modele)
    except ErreurModele as e:
        parser.error(f"Modèle d'IA indisponible : {e}")

    jeu = charger_jeu(args.jeu, args.partie, args.niveau)
    if args.limite:
        jeu.echantillons = jeu.echantillons[: args.limite]
    print(f"{len(jeu.echantillons)} plans à évaluer…", file=sys.stderr)

    resultats, resume, chemin = executer(jeu, modele, args.partie, args.paralleles)
    for r in resultats:
        if r.extraction.piece is None:
            print(f"Échec {r.identifiant} : {r.extraction.erreur}", file=sys.stderr)
    print(tableau(resume))
    print(f"\nDétail : {chemin}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
