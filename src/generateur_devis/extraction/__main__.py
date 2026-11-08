"""Extraire un plan en ligne de commande.

Usage :
    uv run python -m generateur_devis.extraction PLAN.pdf --modele claude-code:sonnet
    uv run python -m generateur_devis.extraction PLAN.pdf --modele openrouter:<modèle> --sortie fiche.json
"""

import argparse
import sys
from pathlib import Path

from generateur_devis.extraction import charger_plan, extraire
from generateur_devis.llm import creer_modele


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--modele", default="claude-code:sonnet")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--sortie", type=Path, help="Fichier où écrire la fiche JSON")
    args = parser.parse_args()

    plan = charger_plan(args.plan, dpi=args.dpi)
    resultat = extraire(plan, creer_modele(args.modele))

    cout = f"{resultat.cout_usd:.4f} $" if resultat.cout_usd is not None else "inconnu"
    print(
        f"Modèle : {resultat.modele} | prompt {resultat.version_prompt} | "
        f"{len(resultat.reponses)} appel(s) | {resultat.duree_s:.1f} s | coût : {cout}"
        + (" | (cache)" if resultat.depuis_cache else ""),
        file=sys.stderr,
    )
    if resultat.piece is None:
        print(f"Échec : {resultat.erreur}", file=sys.stderr)
        return 1
    for probleme in resultat.problemes:
        print(f"Problème de cohérence : {probleme}", file=sys.stderr)

    fiche = resultat.piece.model_dump_json(indent=2, exclude_none=True)
    if args.sortie:
        args.sortie.write_text(fiche + "\n", encoding="utf-8")
        print(f"Fiche écrite dans {args.sortie}", file=sys.stderr)
    else:
        print(fiche)
    return 0


if __name__ == "__main__":
    sys.exit(main())
