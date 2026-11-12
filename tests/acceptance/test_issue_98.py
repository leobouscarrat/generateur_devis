"""Acceptance #98 : proposition dont la ligne a disparu → message clair, pas de plantage.

Connexion simulée par ``session_state[CLE_AUTEUR]`` (aucun secret lu), proposition
posée en ``session_state`` (aucun appel IA), base seedée en mémoire.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from generateur_devis.admin_agent import ModificationAdmin, PropositionAdmin
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.ui import admin as admin_module
from generateur_devis.ui.admin import CLE_AUTEUR, CLE_PROPOSITION_ADMIN


@pytest.fixture(autouse=True)
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
    monkeypatch.setattr(admin_module, "get_session", fabrique)
    return fabrique


def _app() -> None:
    from generateur_devis.ui.admin import main

    main()


def _proposition_ligne_disparue() -> PropositionAdmin:
    return PropositionAdmin(
        modifications=[
            ModificationAdmin(
                type="mise_a_jour",
                table="matieres",
                ligne_id="MATIERE_RETIREE",
                champ="prix_eur_kg",
                valeur=1.25,
                justification="ligne absente de la base",
            )
        ]
    )


def test_ligne_disparue_message_clair_et_retour_a_la_saisie():
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_AUTEUR] = "methodes"
    at.session_state[CLE_PROPOSITION_ADMIN] = _proposition_ligne_disparue()
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    erreurs = [e.value for e in at.error]
    assert any("ne correspond plus à la base" in e for e in erreurs), erreurs
    assert any("MATIERE_RETIREE" in e for e in erreurs), erreurs
    libelles = [b.label for b in at.button]
    assert "✅ Accepter et appliquer" not in libelles
    assert "Nouvelle demande" in libelles
    # Le reste de l'écran est toujours rendu (consultation + historique).
    assert any("Consulter les référentiels" in e.label for e in at.expander)
    assert any("Historique" in e.label for e in at.expander)

    next(b for b in at.button if b.label == "Nouvelle demande").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert CLE_PROPOSITION_ADMIN not in at.session_state
    assert "Proposer la modification" in [b.label for b in at.button]
