"""Générateur de plans de tôlerie avec leur bonne réponse (jeu d'évaluation A)."""

import json
import random
from pathlib import Path

from etude_extraction.generateur.dessin import dessiner
from etude_extraction.generateur.modele import (
    ERREURS,
    INCOHERENCES,
    tirer_piece,
    tirer_piece_erronee,
)
from etude_extraction.generateur.verite import verite

RACINE = Path(__file__).resolve().parents[3]
DOSSIER_GENERE = RACINE / "data" / "generated" / "tolerie"
DOSSIER_ERREURS = RACINE / "data" / "generated" / "tolerie_erreurs"
GRAINES = {"dev": 1001, "test": 2002}
GRAINES_ERREURS = {"dev": 3003, "test": 4004}
DOSSIER_INCOHERENCES = RACINE / "data" / "generated" / "tolerie_incoherences"
GRAINES_INCOHERENCES = {"dev": 5005, "test": 6006}


def generer_piece(graine: int, identifiant: str, dossier: Path, erreur: str | None = None) -> Path:
    """Génère `identifiant.pdf` (plan) et `identifiant.json` (bonne réponse).

    Avec `erreur`, le plan est volontairement erroné et `identifiant.erreur.json` décrit l'erreur.
    """
    rng = random.Random(f"{graine}-{identifiant}")
    if erreur is None:
        spec, geo = tirer_piece(rng, identifiant)
    else:
        spec, geo = tirer_piece_erronee(rng, identifiant, erreur)
        (dossier / f"{identifiant}.erreur.json").write_text(
            json.dumps({"type": erreur, **spec.erreur_detail}), encoding="utf-8"
        )
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


def _generer_erronees(
    partie: str, nombre: int, dossier: Path, graine: int, types: list[str], prefixe: str
) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    for i in range(nombre):
        identifiant = f"{partie}-{prefixe}{i:03d}"
        if not (dossier / f"{identifiant}.json").exists():
            generer_piece(graine, identifiant, dossier, types[i % len(types)])
    return dossier


def generer_jeu_erreurs(partie: str, nombre: int, dossier: Path | None = None) -> Path:
    """Plans volontairement erronés (niveau E) : les types d'erreur sont répartis à tour de rôle."""
    return _generer_erronees(
        partie,
        nombre,
        dossier or DOSSIER_ERREURS / partie,
        GRAINES_ERREURS[partie],
        list(ERREURS),
        "e",
    )


def generer_jeu_incoherences(partie: str, nombre: int, dossier: Path | None = None) -> Path:
    """Plans avec une information invraisemblable (quantité, position, traitement)."""
    return _generer_erronees(
        partie,
        nombre,
        dossier or DOSSIER_INCOHERENCES / partie,
        GRAINES_INCOHERENCES[partie],
        list(INCOHERENCES),
        "i",
    )
