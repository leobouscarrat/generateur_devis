"""Tests d'acceptance de l'issue #34 : agent conversationnel d'administration.

Couverture des critères (1:1) — les critères déjà couverts par les tests
unitaires (tests/test_admin_agent.py, tests/test_formatage.py) sont
référencés, pas dupliqués :
- Whitelist + rejet hors whitelist → test_admin_agent (3 tests dédiés)
- Validation métier (ligne, prix > 0, FK, types) → test_admin_agent
- Réponse non-JSON → erreur lisible → test_admin_agent
- Texte libre → diff → acceptation → écriture + audit → test_bout_en_bout
- Avant/après lu en base → test_admin_agent::test_avant_apres_lu_en_base
- Refus → aucune écriture → test_admin_agent::test_refus_aucune_ecriture
- Précision d'affichage par type de champ → tests/test_formatage.py
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis import admin_agent
from generateur_devis.admin_agent import proposer_modifications
from generateur_devis.data.audit import historique
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, Matiere, Poste
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


def test_bout_en_bout_texte_diff_acceptation_audit(monkeypatch, session):
    """Texte libre → diff → acceptation → écriture + audit daté et attribué (§12)."""

    class FauxModele:
        def generer(self, systeme, message, images):
            return ReponseModele(
                texte=json.dumps({
                    "modifications": [
                        {"type": "mise_a_jour", "table": "matieres", "ligne_id": "S235JR",
                         "champ": "prix_eur_kg", "valeur": 1.25,
                         "justification": "nouveau prix fournisseur"},
                        {"type": "mise_a_jour", "table": "postes", "ligne_id": "LASER_3KW",
                         "champ": "taux_horaire_eur_h", "valeur": 130.0,
                         "justification": "révision tarifaire"},
                    ]
                }),
                modele="test", duree_s=0.0,
            )

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())

    proposition = proposer_modifications(
        "le S235JR passe à 1,25 €/kg et le laser à 130 €/h", "test", session
    )
    assert len(proposition.modifications) == 2
    # L'affichage avant/après lit la valeur actuelle en base, formatée.
    lignes = proposition.ligne_avant_apres(session)
    assert lignes[0][3] == "1.10" and lignes[0][4] == "1.25"
    assert lignes[1][3] == "120.00" and lignes[1][4] == "130.00"

    # Acceptation explicite → écriture + audit.
    nb = proposition.appliquer("acheteur", session)
    session.commit()
    assert nb == 2
    assert session.get(Matiere, "S235JR").prix_eur_kg == pytest.approx(1.25)
    assert session.get(Poste, "LASER_3KW").taux_horaire_eur_h == pytest.approx(130.0)

    audit = historique(session)
    assert len(audit) == 2
    assert all(a.auteur == "acheteur" for a in audit)  # attribuée
    assert all(a.date is not None for a in audit)  # datée


def test_bout_en_bout_ambigu_remarque_sans_modification(monkeypatch, session):
    """Demande ambiguë → remarque explicative, aucune modification proposée."""

    class FauxModele:
        def generer(self, systeme, message, images):
            return ReponseModele(
                texte=json.dumps({
                    "modifications": [],
                    "remarque": "précisez la matière concernée (S235JR ou autre ?)",
                }),
                modele="test", duree_s=0.0,
            )

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())

    proposition = proposer_modifications("augmente le prix de l'acier", "test", session)
    assert proposition.modifications == []
    assert "précisez" in proposition.remarque
