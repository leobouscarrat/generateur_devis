"""Acceptance de l'issue #77 : l'agent admin reçoit l'index des référentiels.

Avant le correctif, le prompt ne contenait que la demande : l'agent ne pouvait
relier « le S235JR », « le laser » ou « le modèle d'extraction » à aucune
ligne. L'appel IA est bouchonné : on vérifie le prompt réellement envoyé et
le parcours demande métier → diff valide.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis import admin_agent
from generateur_devis.admin_agent import proposer_modifications
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.llm.base import ReponseModele


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed(session)
    yield session
    session.close()


def test_demande_metier_prompt_avec_index_et_diff_valide(monkeypatch, session):
    recus: dict[str, str] = {}

    class FauxModele:
        def generer(self, systeme, message, images):
            recus["systeme"], recus["message"] = systeme, message
            return ReponseModele(
                texte=json.dumps(
                    {
                        "modifications": [
                            {
                                "type": "mise_a_jour",
                                "table": "matieres",
                                "ligne_id": "S235JR",
                                "champ": "prix_eur_kg",
                                "valeur": 1.25,
                                "justification": "nouveau prix du S235JR",
                            }
                        ]
                    }
                ),
                modele="test",
                duree_s=0.0,
            )

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())

    proposition = proposer_modifications("le S235JR passe à 1,25 €/kg", "test", session)

    message = recus["message"]
    # La demande métier et l'index des lignes existantes sont transmis.
    assert "le S235JR passe à 1,25 €/kg" in message
    assert "S235JR (acier, S235JR, EN 10025-2)" in message
    assert "LASER_3KW (Laser fibre 3 kW)" in message
    assert "modele_extraction" in message
    assert "historique_devis" not in message
    # Confidentialité : pas de secteur ni de marge client.
    assert "Poids lourds" not in message
    assert "marge_specifique" not in message
    # Le prompt système dit d'utiliser l'index, sans inventer d'identifiant.
    assert "N'invente jamais un identifiant" in recus["systeme"]
    # Le diff reste validé et affichable comme avant.
    assert proposition.ligne_avant_apres(session) == [
        ("matieres", "S235JR", "prix_eur_kg", "1.10", "1.25")
    ]
