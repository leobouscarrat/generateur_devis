"""Acceptance #59 : profil de pliage absent → message qui guide, bloqué au formulaire.

Bout en bout avec ``streamlit.testing.v1.AppTest`` : une pièce extraite sans
profil de pliage (cas du gousset plat Olin) est déposée dans ``session_state``
comme après ``orchestrer_devis``. L'écran doit expliquer sous le tableau d'où
vient le vide, bloquer le recalcul au formulaire avec un message qui guide
(pièce plate = une seule aile ; hors périmètre V1 → « Retour au dépôt »), et ne
plus montrer l'erreur moteur « impossible de construire le flan ».
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.schema.piece import (
    Champ,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Trou,
)
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def piece_sans_profil() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=None,
        contours=Contours(trous=[Trou(forme="rond", diametre=8.0, quantite=1)]),
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def test_profil_absent_message_qui_guide_sans_erreur_moteur():
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_sans_profil(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.run()

    assert not at.exception, [e.value for e in at.exception]

    # Sous le tableau : origine du vide, avec ⛔.
    captions = [c.value for c in at.caption]
    assert any(c.startswith("⛔ Profil de pliage : non lu sur le plan") for c in captions), captions

    # Erreur bloquante au formulaire, qui guide et nomme le hors-périmètre.
    erreurs = [e.value for e in at.error]
    assert any(
        "Profil de pliage vide" in e and "hors périmètre V1" in e and "une seule aile" in e
        for e in erreurs
    ), erreurs
    # Le message moteur n'est plus atteint.
    assert not [e for e in erreurs if "impossible de construire le flan" in e]

    # Recalcul bloqué, mais formulaire, assistant et retour rendus.
    assert not [b for b in at.button if b.label == "Valider la pièce"]
    assert len(at.dataframe) == 2
    assert len(at.text_area) == 1
    assert len([b for b in at.button if b.label == "Retour au dépôt"]) == 1
