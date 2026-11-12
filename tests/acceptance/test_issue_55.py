"""Acceptance #55 : la matière choisie au dépôt est respectée, plus de bascule sur 304L.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
est déposée dans ``session_state`` comme le fait l'écran de dépôt après
``orchestrer_devis`` (``CLE_RESULTAT`` → ``ResultatDevis``, ``CLE_CONTEXTE``
avec le choix matière du dépôt), puis ``main()`` route vers l'écran de
validation. La base locale seedée (``data/devis.db``, via ``get_session``) est
utilisée telle quelle ; aucun devis n'est émis (pas d'écriture en base).
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
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_DEVIS, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def piece_support(designation: str | None) -> PieceExtraite:
    """Le « SUPPORT » du §8 (piece_003), désignation matière au choix."""
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur=designation), epaisseur=Champ[float](valeur=2.0)
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


def _lancer_validation(designation: str | None, matiere_depot: str | None) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(
        piece=piece_support(designation), matiere_id=matiere_depot
    )
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
        "matiere_id": matiere_depot,
    }
    return at.run()


def _liste_matiere(at: AppTest):
    return next(s for s in at.selectbox if s.label == "Matière")


def _textes(at: AppTest) -> list[str]:
    return [e.value for e in (*at.caption, *at.error, *at.warning)]


def test_matiere_du_depot_preselectionnee_puis_validee():
    at = _lancer_validation(designation=None, matiere_depot="S235JR")
    assert not at.exception, [e.value for e in at.exception]

    assert _liste_matiere(at).value.startswith("S235JR — ")
    assert "Matière : choisie au dépôt (absente du plan)." in _textes(at)

    # Le devis validé porte la matière du dépôt (pas 304L).
    next(t for t in at.text_input if t.label.startswith("Votre nom")).input("Testeur").run()
    next(b for b in at.button if b.label == "Valider la pièce").click().run()
    assert not at.exception, [e.value for e in at.exception]
    devis = at.session_state[CLE_DEVIS]
    assert devis.matiere_id == "S235JR"
    assert devis.piece_validee.matiere.designation.valeur == "S235JR"


def test_conflit_depot_plan_signale_et_depot_retenu():
    at = _lancer_validation(designation="304L", matiere_depot="S235JR")
    assert not at.exception, [e.value for e in at.exception]

    assert _liste_matiere(at).value.startswith("S235JR — ")
    assert any("S235JR" in w.value and "« 304L »" in w.value for w in at.warning)


def test_matiere_inconnue_aucune_preselection_et_blocage():
    at = _lancer_validation(designation="16 GAUGE A36 STEEL", matiere_depot=None)
    assert not at.exception, [e.value for e in at.exception]

    # Liste vide : jamais de repli sur l'index 0 (304L).
    liste = _liste_matiere(at)
    assert liste.value is None
    attendu = (
        "Matière : « 16 GAUGE A36 STEEL » lue sur le plan, inconnue du référentiel : à choisir."
    )
    assert "⛔ " + attendu in [c.value for c in at.caption]
    assert any(attendu in e.value for e in at.error)
    # Recalcul et validation bloqués, reste du formulaire rendu.
    assert not [b for b in at.button if b.label == "Valider la pièce"]
    assert len(at.dataframe) == 2
    assert len(at.text_area) == 1

    # Choix explicite → déblocage.
    s235 = next(o for o in liste.options if o.startswith("S235JR — "))
    liste.select(s235).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not [e for e in at.error if "Saisie incomplète" in e.value]
    assert [b for b in at.button if b.label == "Valider la pièce"]


def test_matiere_absente_sans_choix_au_depot():
    at = _lancer_validation(designation=None, matiere_depot=None)
    assert not at.exception, [e.value for e in at.exception]

    assert _liste_matiere(at).value is None
    assert "⛔ Matière : absente du plan et non choisie au dépôt : à choisir." in [
        c.value for c in at.caption
    ]
    assert not [b for b in at.button if b.label == "Valider la pièce"]


def test_libelle_matiere_du_depot():
    at = AppTest.from_function(_app, default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s for s in at.selectbox if s.label == "Matière (prioritaire sur le plan)"]
