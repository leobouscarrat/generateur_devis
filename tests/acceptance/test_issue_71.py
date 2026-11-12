"""Tests d'acceptance de l'issue #71 : marges bornées dans l'agent admin.

Couverture des critères (1:1) — les critères déjà couverts par les tests
unitaires sont référencés, pas dupliqués :
- Borne écrite une seule fois (`marge_valide`) → tests/test_devis.py::test_marge_valide
  + test_changer_marge_invalide (``Devis.changer_marge`` délègue au prédicat)
- Refus à la proposition, base inchangée → test_marge_defaut_100_pct_refusee
- Re-validation à `appliquer`, sans audit →
  test_admin_agent::test_appliquer_revalide_la_marge_sans_audit
- Bornes 0 et marge_max (0.6, issue #102) acceptées, autres paramètres non affectés →
  test_admin_agent::test_marge_defaut_aux_bornes_acceptee,
  test_rayon_pliage_defaut_parametre_administrable
- Règle 7 de `CONSIGNES_ADMIN` → test_admin_agent::test_prompt_admin_enonce_la_borne_des_marges
- Garde-fou création → test_admin_agent::test_clients_et_parametres_non_creables
- Parcours accepté de bout en bout → test_marge_defaut_30_pct_acceptee
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis import admin_agent
from generateur_devis.admin_agent import ErreurAdmin, proposer_modifications
from generateur_devis.data.acces import get_parametre
from generateur_devis.data.audit import historique
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.llm.base import ReponseModele


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def _faux_modele(monkeypatch, valeur: str) -> None:
    class FauxModele:
        def generer(self, systeme, message, images):
            return ReponseModele(
                texte=json.dumps(
                    {
                        "modifications": [
                            {
                                "type": "mise_a_jour",
                                "table": "parametres",
                                "ligne_id": "marge_defaut",
                                "champ": "valeur",
                                "valeur": valeur,
                                "justification": "demande direction",
                            },
                        ]
                    }
                ),
                modele="test",
                duree_s=0.0,
            )

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())


def test_marge_defaut_100_pct_refusee(monkeypatch, session):
    """« La marge par défaut passe à 100 % » : aucune proposition, rien à afficher."""
    _faux_modele(monkeypatch, "1")
    with pytest.raises(ErreurAdmin, match="Marge invalide") as exc:
        proposer_modifications("la marge par défaut passe à 100 %", "test", session)
    assert "fraction comprise entre 0 (incluse) et 1 (exclue)" in str(exc.value)
    session.commit()
    assert get_parametre("marge_defaut", session) == 0.25
    assert historique(session) == []


def test_marge_defaut_30_pct_acceptee(monkeypatch, session):
    """« La marge par défaut passe à 30 % » : proposée, appliquée, auditée."""
    _faux_modele(monkeypatch, "0.30")
    proposition = proposer_modifications("la marge par défaut passe à 30 %", "test", session)
    proposition.appliquer("direction", session)
    session.commit()
    assert get_parametre("marge_defaut", session) == 0.30
    audit = historique(session, table_nom="parametres", ligne_id="marge_defaut")
    assert len(audit) == 1
    assert audit[0].auteur == "direction"
