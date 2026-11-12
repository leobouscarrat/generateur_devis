"""Acceptance #69 : la cotation du profil se corrige à l'écran de validation.

Bout en bout avec ``streamlit.testing.v1.AppTest`` : une pièce à 2 plis dont la
cotation n'a pas été lue (``"inconnue"``) est déposée dans ``session_state``.
Le champ « Cotes du profil » est vide avec un ⛔ sans jargon, le recalcul est
bloqué au formulaire ; un choix suffit à produire le chiffrage.
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


def piece_z(cotation: str) -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation=cotation,
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.0, quantite=1)]),
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer(cotation: str) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_z(cotation), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    return at.run()


def _selecteur_cotes(at: AppTest):
    return next(s for s in at.selectbox if s.label == "Cotes du profil")


def test_cotation_inconnue_bloque_puis_choix_debloque():
    at = _lancer("inconnue")
    assert not at.exception, [e.value for e in at.exception]

    assert _selecteur_cotes(at).value is None
    captions = [c.value for c in at.caption]
    assert any(c.startswith("⛔ Cotes du profil : non précisées") for c in captions), captions
    incompletes = [e.value for e in at.error if "Saisie incomplète" in e.value]
    assert any("extérieur" in e for e in incompletes), incompletes
    assert not [e for e in at.error if "BA et BD" in e.value]
    assert not [b for b in at.button if b.label == "Valider la pièce"]
    assert len(at.dataframe) == 2

    _selecteur_cotes(at).select("exterieure").run()
    assert not at.exception, [e.value for e in at.exception]
    assert not [e for e in at.error if "Saisie incomplète" in e.value]
    assert [b for b in at.button if b.label == "Valider la pièce"]


def test_cotation_lue_pre_remplie_sans_blocage():
    at = _lancer("exterieure")
    assert not at.exception, [e.value for e in at.exception]
    assert _selecteur_cotes(at).value == "exterieure"
    captions = [c.value for c in at.caption]
    assert "Cotes du profil : lues sur le plan." in captions, captions
    assert not [c for c in captions if c.startswith("⛔ Cotes du profil")]
    assert [b for b in at.button if b.label == "Valider la pièce"]
