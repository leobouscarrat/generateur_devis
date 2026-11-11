"""Acceptance #58 : l'écran de validation ne plante plus sur une valeur hors bornes.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
est déposée dans ``session_state`` comme le fait l'écran de dépôt après
``orchestrer_devis`` (``CLE_RESULTAT`` → ``ResultatDevis``, ``CLE_CONTEXTE``),
puis ``main()`` route vers l'écran de validation. La base locale seedée
(``data/devis.db``, via ``get_session``) est utilisée telle quelle.
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


def piece_umaine() -> PieceExtraite:
    """Pièce valide (schéma) mais épaisseur lue 0,06 — cas du plan UMaine en pouces."""
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=0.06)
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
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer_validation() -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_umaine(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    return at.run()


def _textes(at: AppTest) -> list[str]:
    return [e.value for e in (*at.caption, *at.error, *at.warning)]


def test_ecran_validation_epaisseur_hors_bornes_sans_plantage():
    at = _lancer_validation()

    # Pas de StreamlitValueBelowMinError ni d'autre exception.
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Validation de la pièce"

    # Champ épaisseur vide (jamais pré-rempli au minimum).
    epaisseur = next(n for n in at.number_input if n.label == "Épaisseur (mm)")
    assert epaisseur.value is None
    # Les autres champs lus sur le plan restent pré-remplis.
    largeur = next(n for n in at.number_input if n.label == "Largeur d'encombrement (mm)")
    assert largeur.value == 60.0

    # ⛔ avec la valeur lue et le minimum.
    bloquants = [t for t in _textes(at) if "⛔" in t and "0,06 mm" in t]
    assert bloquants, _textes(at)
    assert any("minimum 0,1 mm" in t for t in bloquants)

    # Pas de recalcul ni de validation tant que le champ est vide…
    assert not [b for b in at.button if b.label == "Valider la pièce"]
    # …mais le formulaire (data_editor du profil et des trous) et l'assistant
    # de correction restent rendus.
    assert len(at.dataframe) == 2
    assert len(at.text_area) == 1

    # Un seul bouton « Retour au dépôt », en tête.
    retours = [b for b in at.button if b.label == "Retour au dépôt"]
    assert len(retours) == 1

    retours[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert CLE_RESULTAT not in at.session_state
    assert CLE_CONTEXTE in at.session_state  # contexte commercial conservé
    assert at.title[0].value.startswith("Nouveau devis")


def test_ecran_validation_ressaisie_epaisseur_debloque_le_recalcul():
    at = _lancer_validation()
    epaisseur = next(n for n in at.number_input if n.label == "Épaisseur (mm)")
    epaisseur.set_value(2.0).run()

    assert not at.exception, [e.value for e in at.exception]
    assert not [e for e in at.error if "Saisie incomplète" in e.value]
    # Recalcul repris : le bouton de validation est de nouveau rendu.
    assert [b for b in at.button if b.label == "Valider la pièce"]
