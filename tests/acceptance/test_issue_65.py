"""Acceptance #65 : un profil non alterné (ligne supprimée) ne fait plus planter l'écran.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
est déposée dans ``session_state`` comme le fait l'écran de dépôt
(``CLE_RESULTAT`` → ``ResultatDevis``, ``CLE_CONTEXTE``), puis ``main()``
route vers l'écran de validation. Le profil [aile, aile, pli, aile] est l'état
du tableau après suppression d'un pli : avant le correctif, il était chiffré
faux en silence puis ``construire_profil_2d`` levait ``IndexError``.

L'angle hors bornes n'est pas injectable par une pièce valide (le schéma
``Pli`` le refuse) et AppTest ne sait pas éditer un ``st.data_editor`` : ce cas
est couvert par les tests purs de ``tests/test_validation.py``.
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
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def piece_pli_supprime() -> PieceExtraite:
    """Pièce support dont le 1er pli a été supprimé : aile, aile, pli, aile."""
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
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def test_profil_non_alterne_erreur_lisible_sans_plantage():
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_pli_supprime(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.run()

    # Pas d'IndexError ni d'autre exception.
    assert not at.exception, [e.value for e in at.exception]

    # ⛔ unique et lisible sur la 1re ligne fautive.
    alternance = [e.value for e in at.error if "alternent" in e.value]
    assert len(alternance) == 1, [e.value for e in at.error]
    assert "Profil ligne 2" in alternance[0]
    assert "pli attendu" in alternance[0]

    # Ni chiffrage ni validation tant que le profil est incohérent…
    assert not [b for b in at.button if b.label == "Valider la pièce"]
    # …mais le formulaire (profil + trous) reste rendu.
    assert len(at.dataframe) == 2
    assert len([b for b in at.button if b.label == "Retour au dépôt"]) == 1
