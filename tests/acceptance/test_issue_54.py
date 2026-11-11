"""Acceptance #54 : émission sans « Flan introuvable », flan de la pièce validée.

Parcours de l'issue avec ``streamlit.testing.v1.AppTest`` : la pièce
(piece_003, matière non lue sur le plan) est déposée dans ``session_state``
comme le fait l'écran de dépôt quand la matière n'est pas résolue
(``ResultatDevis(piece=..., matiere_id=None)`` → aucun flan initial), la
matière est choisie à la validation, puis le devis est émis.

``get_session`` de l'app est remplacé par une base SQLite en mémoire seedée
(``StaticPool`` : une seule connexion partagée avec le thread du script) —
l'émission écrit dans ``historique_devis`` sans toucher ``data/devis.db``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from generateur_devis.controles_prix import evaluer_controles_prix
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, HistoriqueDevis
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui import app as app_module
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_DEVIS, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def piece_003() -> PieceExtraite:
    """Le « SUPPORT » du §8, matière non désignée (non lue sur le plan)."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
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
        contours=Contours(
            trous=[
                Trou(forme="rond", diametre=8.75, quantite=2),
                Trou(forme="rond", diametre=7.5, quantite=2),
            ],
            coins=[
                CoinCoupe(type="chanfrein", cote1=20.0, quantite=2),
                CoinCoupe(type="chanfrein", cote1=5.0, quantite=2),
            ],
        ),
    )


@pytest.fixture
def fabrique(monkeypatch):
    """Base seedée en mémoire, injectée à la place de ``data/devis.db``."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    fabrique = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with fabrique() as session:
        seed(session)
        session.commit()
    monkeypatch.setattr(app_module, "get_session", fabrique)
    return fabrique


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _valider() -> AppTest:
    """Dépôt sans matière → validation avec S235JR choisie à l'écran."""
    at = AppTest.from_function(_app, default_timeout=30)
    depot = ResultatDevis(piece=piece_003(), matiere_id=None)
    assert depot.flan is None  # le dépôt n'a produit aucun flan
    at.session_state[CLE_RESULTAT] = depot
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    matiere = next(s for s in at.selectbox if s.label == "Matière")
    libelle = next(o for o in matiere.options if o.startswith("S235JR"))
    matiere.set_value(libelle).run()
    next(t for t in at.text_input if t.label.startswith("Votre nom")).set_value("testeur").run()
    next(s for s in at.selectbox if s.label == "Quantité commandée").set_value(100).run()
    next(b for b in at.button if b.label == "Valider la pièce").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Restitution"
    return at


def test_emission_sans_flan_au_depot(fabrique):
    at = _valider()
    devis = at.session_state[CLE_DEVIS]
    # Le devis porte le flan de la pièce validée (§8 : 74,8 × 60 × 2 mm).
    assert devis.flan.largeur_mm == pytest.approx(60.0)
    assert devis.flan.longueur_developpee_mm == pytest.approx(74.8, abs=0.1)

    next(b for b in at.button if b.label == "📤 Émettre le devis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert not [e.value for e in at.error if "Flan introuvable" in e.value]
    assert at.session_state[CLE_DEVIS].statut == "emis"
    assert "pdf_client" in at.session_state
    with fabrique() as session:
        ligne = session.scalar(select(HistoriqueDevis).where(HistoriqueDevis.id == devis.id))
    assert ligne is not None
    assert ligne.matiere_id == "S235JR"
    assert ligne.flan_w_mm == pytest.approx(60.0)
    assert ligne.flan_l_mm == pytest.approx(74.8, abs=0.1)
    # Masse au rectangle englobant : 74,8 × 60 × 2 × 7,85e-6 ≈ 0,0705 kg.
    assert ligne.masse_kg == pytest.approx(0.0705, abs=0.001)


def test_alertes_restitution_recalculees_depuis_le_devis(fabrique):
    """Marge portée à 90 % à la restitution : l'alerte €/kg suit les nouveaux prix.

    Le résultat du dépôt n'a aucune alerte (matière non résolue) : avant le
    correctif, l'écran de restitution n'en affichait donc aucune.
    """
    at = _valider()
    assert at.session_state[CLE_RESULTAT].alertes_controles == []
    next(n for n in at.number_input if n.label == "Marge").set_value(0.90)
    next(b for b in at.button if b.label == "Appliquer la marge").click().run()
    assert not at.exception, [e.value for e in at.exception]

    devis = at.session_state[CLE_DEVIS]
    assert devis.marge == pytest.approx(0.90)
    with fabrique() as session:
        attendues = evaluer_controles_prix(
            devis.chiffrage, devis.piece_validee, devis.flan, devis.matiere_id, session
        )
    # Coût palier 100 ≈ 1,24 € (sans composants) → prix ≈ 12,4 € pour ≈ 0,06 kg
    # net, soit ≈ 200 €/kg : hors fourchette [2, 150] €/kg du seed.
    assert any(a.regle == "prix_au_kg" for a in attendues)
    # AppTest retire l'emoji de tête (« ⚖️ ») de la valeur des st.warning.
    affichees = [w.value for w in at.warning if "Contrôle prix" in w.value]
    assert affichees == [f"Contrôle prix ({a.regle}) : {a.message}" for a in attendues]
