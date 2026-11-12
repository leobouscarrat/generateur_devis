"""Acceptance #68 : rechargement de page → extraction reprise sans nouvel appel IA.

Le parcours dépôt → reprise (redépôt du même plan après F5) est couvert au niveau
pipeline (``tests/test_pipeline.py``) : ``AppTest`` ne pilote pas
``st.file_uploader``. Ici, on vérifie les messages des écrans :

- validation : avertissement « ne rechargez pas » toujours présent, et mention
  « extraction reprise sans nouvel appel IA » quand ``extraction_reprise`` ;
- restitution : avertissement tant que le devis n'est pas émis ;
- dépôt : la mémoire partagée du serveur est bien branchée sur le pipeline.

``get_session`` est remplacé par une base SQLite seedée en mémoire.
"""

from __future__ import annotations

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

REPRISE = "extraction reprise sans nouvel appel IA"
RECHARGEMENT = "Ne rechargez pas la page"


def piece_support() -> PieceExtraite:
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
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
    )


@pytest.fixture
def fabrique(monkeypatch):
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


def _validation(extraction_reprise: bool) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(
        piece=piece_support(), matiere_id="S235JR", extraction_reprise=extraction_reprise
    )
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
        "matiere_id": None,
    }
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _contient(elements, texte: str) -> bool:
    return any(texte in e.value for e in elements)


def test_validation_extraction_reprise_signalee(fabrique):
    at = _validation(extraction_reprise=True)
    assert _contient(at.info, REPRISE)
    assert _contient(at.info, "corrections faites avant un rechargement ne sont pas conservées")
    assert _contient(at.caption, RECHARGEMENT)
    assert _contient(at.caption, "« Retour au dépôt »")


def test_validation_sans_reprise_avertissement_seul(fabrique):
    at = _validation(extraction_reprise=False)
    assert not _contient(at.info, REPRISE)
    assert _contient(at.caption, RECHARGEMENT)


def _restitution(fabrique) -> AppTest:
    at = _validation(extraction_reprise=False)
    next(t for t in at.text_input if t.label.startswith("Votre nom")).set_value("testeur").run()
    next(s for s in at.selectbox if s.label == "Quantité commandée").set_value(100).run()
    next(b for b in at.button if b.label == "Valider la pièce").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Restitution"
    return at


def test_restitution_avertit_tant_que_non_emis(fabrique):
    at = _restitution(fabrique)
    assert at.session_state[CLE_DEVIS].statut != "emis"
    assert _contient(at.caption, RECHARGEMENT)

    next(b for b in at.button if b.label == "📤 Émettre le devis").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state[CLE_DEVIS].statut == "emis"
    assert not _contient(at.caption, RECHARGEMENT)


def test_memoire_extractions_partagee_entre_sessions():
    """Même dict servi à chaque appel (st.cache_resource) : survit à une nouvelle session."""
    memoire = app_module._memoire_extractions()
    assert isinstance(memoire, dict)
    assert app_module._memoire_extractions() is memoire


def test_depot_mentionne_la_reprise(fabrique):
    at = AppTest.from_function(_app, default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert _contient(at.caption, "sans nouvel appel IA")
