"""Acceptance #72 : le rayon propre à chaque pli est conservé et éditable.

1. Reconstruction (hors AppTest, comme ``test_issue_24.py``) : ``_editer_piece``
   rend le tableau initial tel quel ; le ``Pli.rayon_interieur`` extrait survit.
2. Bout en bout (AppTest) : pli coté R1 sur une tôle de 2 mm avec un rayon
   général de 2 mm → l'alerte faisabilité ``rayon_min`` apparaît sur l'écran
   de validation, et la caption sous le tableau cite le rayon lu.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui.app import (
    CLE_CONTEXTE,
    CLE_RESULTAT,
    _editer_piece,
    matiere_initiale,
)
from generateur_devis.ui.pipeline import ResultatDevis


def piece_pli_r1() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut", rayon_interieur=1.0),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.0, quantite=1)]),
    )


def test_reconstruction_conserve_le_rayon_du_pli():
    piece = piece_pli_r1()
    choix = {"S235JR — acier (EN 10025)": "S235JR"}
    matiere = matiere_initiale(None, piece.matiere.designation.valeur, choix.values())
    editee, _, erreurs = _editer_piece(piece, choix, matiere)
    assert erreurs == []
    assert editee is not None
    assert editee.profil_pliage.elements[1].rayon_interieur == 1.0


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def test_alerte_rayon_min_sur_le_rayon_propre_au_pli():
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_pli_r1(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    alertes = [w.value for w in at.warning]
    assert any("Rayon 1 mm < 1 × épaisseur" in w for w in alertes), alertes
    captions = [c.value for c in at.caption]
    assert any("ligne 2 : 1 mm" in c for c in captions), captions
    assert [b for b in at.button if b.label == "Valider la pièce"]
