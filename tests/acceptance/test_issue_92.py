"""Acceptance #92 : modèle d'IA mal configuré → message clair, jamais d'erreur brute.

Couverture des critères :
- Écran devis, désignation mal formée → AppTest du dépôt ci-dessous (vrai
  ``creer_modele`` via ``MODELE_EXTRACTION``, ``extraire`` interdit).
- Clé d'API absente → AppTest ci-dessous (``ErreurModele`` à la construction).
- Assistant de correction → test_correction::test_proposition_modele_mal_configure_cite_la_configuration
  et test_proposition_modele_sans_cle_api_erreur_correction.
- Agent admin, refus à la proposition ET à l'application → tests ci-dessous.
- Règle unique ``verifier_designation`` → tests/test_llm.py.

Aucune écriture en base pour l'écran : la base locale seedée n'est que lue,
comme dans ``test_issue_63.py``.
"""

from __future__ import annotations

import json

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from generateur_devis import admin_agent
from generateur_devis.admin_agent import (
    ErreurAdmin,
    ModificationAdmin,
    PropositionAdmin,
    proposer_modifications,
)
from generateur_devis.data.acces import get_parametre
from generateur_devis.data.audit import historique
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.llm.base import ReponseModele
from generateur_devis.ui import pipeline
from generateur_devis.ui.app import CLE_RESULTAT


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _interdit(*args, **kwargs):
    raise AssertionError("extraction appelée")


def _plan() -> bytes:
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "SUPPORT")
        return doc.tobytes()


def _deposer(monkeypatch) -> AppTest:
    monkeypatch.setattr(pipeline, "extraire", _interdit)
    at = AppTest.from_function(_app, default_timeout=30).run()
    at.file_uploader[0].set_value(("plan.pdf", _plan(), "application/pdf")).run()
    next(b for b in at.button if b.label == "Lancer l'analyse").click().run()
    return at


def _reste_sur_le_depot(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Nouveau devis — dépôt du plan"
    assert CLE_RESULTAT not in at.session_state
    assert any(b.label == "Lancer l'analyse" for b in at.button)
    for e in (*at.error, *at.warning, *at.exception):
        assert "/tmp" not in e.value and "Traceback" not in e.value and ".py" not in e.value


def test_depot_modele_mal_forme_message_clair(monkeypatch):
    monkeypatch.setenv("MODELE_EXTRACTION", "sonnet")
    at = _deposer(monkeypatch)
    _reste_sur_le_depot(at)
    assert [e.value for e in at.error] == [
        "Modèle d'IA mal configuré (paramètre « modele_extraction » ou variable "
        "MODELE_EXTRACTION) : Format attendu « fournisseur:modèle », reçu « sonnet »"
    ]


def test_depot_cle_api_absente_message_clair(monkeypatch):
    monkeypatch.setenv("MODELE_EXTRACTION", "openrouter:modele-x")
    monkeypatch.setattr("generateur_devis.llm.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    at = _deposer(monkeypatch)
    _reste_sur_le_depot(at)
    assert [e.value for e in at.error] == [
        "Modèle d'IA indisponible : openrouter : clé d'API manquante (voir .env.example)"
    ]


# --- Agent admin : modele_extraction mal formé refusé -------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed(session)
    yield session
    session.close()


def test_admin_refuse_modele_mal_forme_a_la_proposition(monkeypatch, session):
    class FauxModele:
        def generer(self, systeme, message, images):
            diff = {
                "modifications": [
                    {
                        "type": "mise_a_jour",
                        "table": "parametres",
                        "ligne_id": "modele_extraction",
                        "champ": "valeur",
                        "valeur": "sonnet",
                        "justification": "demande admin",
                    }
                ]
            }
            return ReponseModele(texte=json.dumps(diff), modele="test", duree_s=0.0)

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())
    with pytest.raises(ErreurAdmin, match="Modèle d'extraction invalide"):
        proposer_modifications("le modèle d'extraction passe à sonnet", "test", session)
    assert get_parametre("modele_extraction", session) == "claude-code:sonnet"
    assert historique(session) == []


def test_admin_refuse_modele_mal_forme_a_l_application(session):
    proposition = PropositionAdmin(
        modifications=[
            ModificationAdmin(
                type="mise_a_jour",
                table="parametres",
                ligne_id="modele_extraction",
                champ="valeur",
                valeur="foo:bar",
                justification="test",
            )
        ]
    )
    with pytest.raises(ErreurAdmin, match="Modèle d'extraction invalide"):
        proposition.appliquer("admin", session)
    assert get_parametre("modele_extraction", session) == "claude-code:sonnet"
    assert historique(session) == []
