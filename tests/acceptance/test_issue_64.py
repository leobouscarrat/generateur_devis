"""Acceptance #64 : document non-plan refusé au dépôt, anomalies de l'IA affichées.

Parcours réels avec ``streamlit.testing.v1.AppTest``, sans appel IA :
- validation : la pièce extraite est posée dans ``session_state`` comme le fait
  le dépôt (``CLE_RESULTAT`` → ``ResultatDevis``) ; ses anomalies doivent
  s'afficher en tête, y compris quand la saisie est bloquée (cas #58) ;
- dépôt : vrai PDF d'une page + vrai ``charger_plan`` ; seul ``extraire`` est
  bouchonné et renvoie une pièce marquée « document non exploitable ».
La base locale seedée (``data/devis.db``, via ``get_session``) n'est que lue.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from generateur_devis.extraction import ResultatExtraction
from generateur_devis.schema.piece import (
    Aile,
    Anomalie,
    Champ,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui import pipeline
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis

PREFIXE = "Signalé à la lecture du plan — "
ANOMALIES = [
    Anomalie(
        type="information_manquante",
        champ="traitement.type",
        description="traitement de surface non indiqué",
    ),
    Anomalie(type="incoherence", champ=None, description="cote 42 contredite par la vue de face"),
]


def piece(epaisseur: float) -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=epaisseur)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
        anomalies=ANOMALIES,
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer_validation(epaisseur: float) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece(epaisseur), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {"client_id": None, "quantites": [1, 100], "nom_modele": "t"}
    return at.run()


@pytest.mark.parametrize("epaisseur", [2.0, 0.06], ids=["formulaire_valide", "saisie_bloquee"])
def test_validation_anomalies_ia_en_tete(epaisseur):
    at = _lancer_validation(epaisseur)

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Validation de la pièce"
    avertissements = [w.value for w in at.warning]
    assert f"{PREFIXE}Information manquante : traitement de surface non indiqué" in (avertissements)
    assert f"{PREFIXE}Incohérence : cote 42 contredite par la vue de face" in avertissements


def test_validation_saisie_bloquee_confirme_le_blocage():
    """Contre-épreuve du cas 0,06 mm : la saisie est bien bloquée (cas #58)."""
    at = _lancer_validation(0.06)
    assert any("Saisie incomplète" in e.value for e in at.error)


def test_depot_document_non_plan_reste_sur_le_depot(monkeypatch):
    import pymupdf

    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "DEVIS N° 42 — Matière : 304L, 2 mm")
        contenu = doc.tobytes()

    devis = piece(2.0)
    devis.anomalies = [
        Anomalie(
            type="illisible",
            champ="document",
            description="Le document est un devis commercial.",
        )
    ]
    monkeypatch.setattr(
        pipeline,
        "extraire",
        lambda document, modele, **kw: ResultatExtraction("test:m", "test", devis, None),
    )
    monkeypatch.setattr(pipeline, "creer_modele", lambda nom: object())

    at = AppTest.from_function(_app, default_timeout=30).run()
    at.file_uploader[0].set_value(("devis.pdf", contenu, "application/pdf")).run()
    next(b for b in at.button if b.label == "Lancer l'analyse").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Nouveau devis — dépôt du plan"
    assert (
        "Ce document n'est pas un plan exploitable : Le document est un devis commercial. "
        "Déposez le plan de la pièce (PDF ou image)."
    ) in [e.value for e in at.error]
    assert CLE_RESULTAT not in at.session_state
