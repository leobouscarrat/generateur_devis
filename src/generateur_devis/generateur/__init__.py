"""Générateur de plans de tôlerie avec leur bonne réponse (jeu d'évaluation A)."""

import json
import random
from pathlib import Path

from generateur_devis.generateur.dessin import dessiner
from generateur_devis.generateur.modele import tirer_piece
from generateur_devis.generateur.verite import verite

RACINE = Path(__file__).resolve().parents[3]
DOSSIER_GENERE = RACINE / "data" / "generated" / "tolerie"
GRAINES = {"dev": 1001, "test": 2002}


def generer_piece(graine: int, identifiant: str, dossier: Path) -> Path:
    """Génère `identifiant.pdf` (plan) et `identifiant.json` (bonne réponse)."""
    rng = random.Random(f"{graine}-{identifiant}")
    spec, geo = tirer_piece(rng, identifiant)
    chemin_pdf = dossier / f"{identifiant}.pdf"
    cotes = dessiner(spec, geo, chemin_pdf)
    bonne_reponse = verite(spec, geo, cotes)
    (dossier / f"{identifiant}.json").write_text(
        bonne_reponse.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    return chemin_pdf


def generer_jeu(partie: str, nombre: int, dossier: Path | None = None) -> Path:
    """Génère (ou complète) le jeu `partie`. Reproductible : même graine, mêmes plans."""
    dossier = dossier or DOSSIER_GENERE / partie
    dossier.mkdir(parents=True, exist_ok=True)
    for i in range(nombre):
        identifiant = f"{partie}-{i:03d}"
        if not (dossier / f"{identifiant}.json").exists():
            generer_piece(GRAINES[partie], identifiant, dossier)
    (dossier / "manifeste.json").write_text(
        json.dumps({"partie": partie, "graine": GRAINES[partie], "nombre": nombre}),
        encoding="utf-8",
    )
    return dossier
