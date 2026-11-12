"""Acceptance #102 : marge de la restitution bornée, saisie en %, refus lisible.

Avant le correctif, la restitution acceptait toute marge 0 ≤ marge < 1
(0,999 → prix × 1000), affichait 0,999 en « 1.00 » (format ``%.2f``),
gardait la saisie refusée dans le champ, et ne signalait pas la marge 0.

Désormais : borne haute administrable ``marge_max`` (seed 60 %), saisie en
pourcentage, refus avec plage et marge appliquée, champ remis à la marge en
vigueur, ⚠️ sur la marge 0, ⛔ + émission désactivée si la marge en vigueur
sort de la plage.

Parcours ``streamlit.testing.v1.AppTest`` sans appel IA, ``get_session``
remplacé par une base SQLite en mémoire seedée.
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


def _fabrique(monkeypatch, marge_defaut: str = "0.25") -> None:
    """Base seedée en mémoire (``marge_max`` = 0.6), ``marge_defaut`` administré."""
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
    """Validation (S235JR, Q 100, sans client → marge_defaut) puis restitution."""
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


def _champ(at: AppTest):
    return next(n for n in at.number_input if n.label == "Marge (%)")


def _appliquer(at: AppTest, pourcentage: float) -> None:
    _champ(at).set_value(pourcentage)
    next(b for b in at.button if b.label == "Appliquer la marge").click().run()
    assert not at.exception, [e.value for e in at.exception]


def _emettre(at: AppTest):
    return next(b for b in at.button if "Émettre le devis" in b.label)


def test_marge_saisie_en_pourcentage(monkeypatch):
    _fabrique(monkeypatch)
    at = _restitution()
    champ = _champ(at)
    assert champ.value == pytest.approx(25.0)
    assert champ.min is None
    assert champ.max is None
    assert not at.error


@pytest.mark.parametrize(
    ("saisie", "affiche"), [(150.0, "150 %"), (99.9, "99,9 %"), (60.1, "60,1 %")]
)
def test_marge_hors_plage_refusee_et_champ_remis(monkeypatch, saisie, affiche):
    _fabrique(monkeypatch)
    at = _restitution()
    devis = at.session_state[CLE_DEVIS]
    prix = [p.prix_unitaire_eur for p in devis.chiffrage.paliers]
    nb_modifications = len(devis.modifications)

    _appliquer(at, saisie)

    # AppTest retire l'emoji de tête (« ⛔ ») de la valeur des st.error.
    assert [e.value for e in at.error] == [
        f"Marge refusée : {affiche} hors de la plage 0 – 60 %. Marge appliquée : 25 %."
    ]
    assert _champ(at).value == pytest.approx(25.0)
    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == pytest.approx(0.25)
    assert [p.prix_unitaire_eur for p in devis.chiffrage.paliers] == prix
    assert len(devis.modifications) == nb_modifications
    assert not _emettre(at).disabled


def test_marge_40_pourcent_appliquee(monkeypatch):
    _fabrique(monkeypatch)
    at = _restitution()

    _appliquer(at, 40.0)

    assert not at.error
    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == pytest.approx(0.40)
    palier = devis.palier_commande()
    assert palier.prix_unitaire_eur == pytest.approx(palier.cout_unitaire_eur / 0.60, rel=1e-9)
    assert _champ(at).value == pytest.approx(40.0)


def test_marge_60_pourcent_borne_incluse(monkeypatch):
    _fabrique(monkeypatch)
    at = _restitution()
    _appliquer(at, 60.0)
    assert not at.error
    assert at.session_state[CLE_DEVIS].marge == pytest.approx(0.60)


def test_marge_zero_acceptee_avec_avertissement(monkeypatch):
    _fabrique(monkeypatch)
    at = _restitution()
    assert not [w for w in at.warning if "prix de revient" in w.value]

    _appliquer(at, 0.0)

    assert not at.error
    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == 0.0
    assert [w.value for w in at.warning if "prix de revient" in w.value] == [
        "Marge 0 % : vente au prix de revient."
    ]
    assert not _emettre(at).disabled


def test_marge_en_vigueur_hors_plage_bloque_l_emission(monkeypatch):
    """``marge_defaut`` muté en base à 0,97 : pas de plantage, ⛔ et émission désactivée."""
    _fabrique(monkeypatch, marge_defaut="0.97")
    at = _restitution()
    assert _champ(at).value == pytest.approx(97.0)
    assert [e.value for e in at.error] == [
        "Marge refusée : 97 % hors de la plage 0 – 60 %. "
        "Corrigez la marge pour pouvoir émettre le devis."
    ]
    assert _emettre(at).disabled

    _appliquer(at, 30.0)

    assert not at.error
    assert at.session_state[CLE_DEVIS].marge == pytest.approx(0.30)
    assert not _emettre(at).disabled
