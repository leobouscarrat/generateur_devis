"""Acceptance #60 : paliers de quantité normalisés, prix provisoire à 2 décimales.

Parcours ``streamlit.testing.v1.AppTest`` sans appel IA :

- dépôt : la saisie « 10, 1, 10 » est normalisée en paliers 1 puis 10 et la
  légende « Paliers retenus » le montre ; « 10,,20 » reste acceptée ;
- validation : avec les paliers normalisés du contexte, le tableau « Prix
  provisoire » affiche coût et prix unitaires à 2 décimales (chaînes formatées,
  plus de ``54.3600``) et « Quantité commandée » propose 1 puis 10.

``get_session`` de l'app est remplacé par une base SQLite en mémoire seedée.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
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
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_DEVIS, CLE_RESULTAT, parser_quantites
from generateur_devis.ui.pipeline import ResultatDevis

LIBELLE_QUANTITES = "Quantités (séparées par des virgules)"


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


def _depot(saisie: str) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    next(t for t in at.text_input if t.label == LIBELLE_QUANTITES).set_value(saisie).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _paliers_retenus(at: AppTest) -> list[str]:
    return [c.value for c in at.caption if c.value.startswith("Paliers retenus")]


def test_depot_doublons_et_desordre_normalises(fabrique):
    at = _depot("10, 1, 10")
    assert not at.error
    assert _paliers_retenus(at) == ["Paliers retenus : 1, 10"]


def test_depot_segment_vide_accepte(fabrique):
    at = _depot("10,,20")
    assert not at.error
    assert _paliers_retenus(at) == ["Paliers retenus : 10, 20"]


def test_depot_saisie_invalide(fabrique):
    at = _depot("10, 0")
    assert [e.value for e in at.error] == [
        "Quantités invalides : entiers positifs séparés par des virgules."
    ]
    assert _paliers_retenus(at) == []
    assert next(b for b in at.button if b.label == "Lancer l'analyse").disabled


def _piece() -> PieceExtraite:
    """Pièce pliée simple (2 ailes, 1 pli), matière choisie à l'écran."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[Aile(longueur=42.0), Pli(angle=90.0, sens="haut"), Aile(longueur=22.0)],
        ),
    )


def test_validation_prix_provisoire_deux_decimales(fabrique):
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=_piece(), matiere_id=None)
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": parser_quantites("10, 1, 10"),
        "nom_modele": "test",
    }
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    matiere = next(s for s in at.selectbox if s.label == "Matière")
    matiere.set_value(next(o for o in matiere.options if o.startswith("S235JR"))).run()
    assert not at.exception, [e.value for e in at.exception]

    assert next(s for s in at.selectbox if s.label == "Quantité commandée").options == [
        "1",
        "10",
    ]
    (tableau,) = at.table
    df = tableau.value
    assert list(df["Quantité"]) == [1, 10]
    for colonne in ("Coût unitaire (€)", "Prix unitaire (€)"):
        valeurs = list(df[colonne])
        assert len(valeurs) == 2
        # Chaînes formatées à 2 décimales exactement (avant : float → « 54.3600 »).
        assert all(isinstance(v, str) and re.fullmatch(r"\d+\.\d{2}", v) for v in valeurs), valeurs

    # Ventilation des coûts (site frère) : chaînes à 2 décimales aussi.
    (ventilation,) = [d.value for d in at.dataframe if "Variable (€/pièce)" in d.value.columns]
    for colonne in ("Variable (€/pièce)", "Fixe (€/lot)"):
        valeurs = list(ventilation[colonne])
        assert all(isinstance(v, str) and re.fullmatch(r"\d+\.\d{2}", v) for v in valeurs), valeurs

    # Parcours jusqu'au devis : seuls les paliers 1 et 10 subsistent.
    next(t for t in at.text_input if t.label.startswith("Votre nom")).set_value("testeur").run()
    next(b for b in at.button if b.label == "Valider la pièce").click().run()
    assert not at.exception, [e.value for e in at.exception]
    devis = at.session_state[CLE_DEVIS]
    assert [p.quantite for p in devis.chiffrage.paliers] == [1, 10]
    vue_client = at.dataframe[0].value
    assert list(vue_client["quantite"]) == [1, 10]
    # Vue client : prix à 2 décimales (un float « 71.60 » s'afficherait « 71.6 »).
    for colonne in ("prix_unitaire_eur", "prix_total_eur"):
        valeurs = list(vue_client[colonne])
        assert all(isinstance(v, str) and re.fullmatch(r"\d+\.\d{2}", v) for v in valeurs), valeurs
