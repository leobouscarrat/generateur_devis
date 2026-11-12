"""Acceptance #62 : champ marge de la restitution sans bornes de widget.

Avant le correctif, ``st.number_input("Marge", min_value=0.0, max_value=0.95)``
recevait la marge administrée telle quelle : ``marge_defaut`` à 0,97 (ou
négative) faisait planter l'écran (``StreamlitValueAboveMaxError`` /
``BelowMinError``). La seule règle est désormais ``Devis.changer_marge``
(0 ≤ marge < 1) ; une saisie refusée affiche un ⛔ sans rien modifier.

Parcours ``streamlit.testing.v1.AppTest`` sans appel IA, ``get_session``
remplacé par une base SQLite en mémoire seedée où ``marge_defaut`` est muté.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, Parametre
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
)
from generateur_devis.ui import app as app_module
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_DEVIS, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def _fabrique(monkeypatch, marge_defaut: str):
    """Base seedée en mémoire, ``marge_defaut`` administré à la valeur donnée."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    fabrique = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with fabrique() as session:
        seed(session)
        session.get(Parametre, "marge_defaut").valeur = marge_defaut
        session.commit()
    monkeypatch.setattr(app_module, "get_session", fabrique)


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _piece() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[Aile(longueur=42.0), Pli(angle=90.0, sens="haut"), Aile(longueur=22.0)],
        ),
    )


def _restitution() -> AppTest:
    """Validation (S235JR, Q 100) puis écran de restitution."""
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=_piece(), matiere_id=None)
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    matiere = next(s for s in at.selectbox if s.label == "Matière")
    matiere.set_value(next(o for o in matiere.options if o.startswith("S235JR"))).run()
    next(t for t in at.text_input if t.label.startswith("Votre nom")).set_value("testeur").run()
    next(s for s in at.selectbox if s.label == "Quantité commandée").set_value(100).run()
    next(b for b in at.button if b.label == "Valider la pièce").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Restitution"
    return at


def _marge(at: AppTest):
    return next(n for n in at.number_input if n.label == "Marge")


def _appliquer(at: AppTest, valeur: float) -> None:
    _marge(at).set_value(valeur)
    next(b for b in at.button if b.label == "Appliquer la marge").click().run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("marge_defaut", ["0.97", "-0.1"])
def test_marge_administree_hors_anciennes_bornes_sans_plantage(monkeypatch, marge_defaut):
    _fabrique(monkeypatch, marge_defaut)
    at = _restitution()
    assert at.session_state[CLE_DEVIS].marge == pytest.approx(float(marge_defaut))
    champ = _marge(at)
    assert champ.value == pytest.approx(float(marge_defaut))
    assert champ.min is None
    assert champ.max is None


@pytest.mark.parametrize("saisie", [1.0, -0.01])
def test_saisie_hors_bornes_refusee_sans_effet(monkeypatch, saisie):
    _fabrique(monkeypatch, "0.25")
    at = _restitution()
    devis = at.session_state[CLE_DEVIS]
    prix = [p.prix_unitaire_eur for p in devis.chiffrage.paliers]
    nb_modifications = len(devis.modifications)

    _appliquer(at, saisie)

    # AppTest retire l'emoji de tête (« ⛔ ») de la valeur des st.error.
    assert [e.value for e in at.error] == [f"Marge invalide : {saisie}."]
    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == pytest.approx(0.25)
    assert [p.prix_unitaire_eur for p in devis.chiffrage.paliers] == prix
    assert len(devis.modifications) == nb_modifications


def test_marge_096_appliquee_depuis_l_ecran(monkeypatch):
    _fabrique(monkeypatch, "0.25")
    at = _restitution()

    _appliquer(at, 0.96)

    assert not at.error
    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == pytest.approx(0.96)
    palier = devis.palier_commande()
    assert palier.prix_unitaire_eur == pytest.approx(palier.cout_unitaire_eur / 0.04, rel=1e-9)
