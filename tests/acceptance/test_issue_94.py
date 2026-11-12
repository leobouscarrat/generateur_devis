"""Acceptance #94 : consulter les valeurs actuelles des référentiels sans IA.

Parcours réel de l'écran d'administration avec ``streamlit.testing.v1.AppTest``.
La connexion est simulée par ``session_state[CLE_AUTEUR]`` (aucun secret lu) ;
``get_session`` de l'écran admin pointe vers une base seedée en mémoire.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

import generateur_devis.ui.admin as admin_module
from generateur_devis.admin_agent import ModificationAdmin, PropositionAdmin
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, BorneControle
from generateur_devis.ui.admin import CLE_AUTEUR, CLE_PROPOSITION_ADMIN


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
    monkeypatch.setattr(admin_module, "get_session", fabrique)
    return fabrique


def _app() -> None:
    from generateur_devis.ui.admin import main

    main()


def _connecte(proposition: PropositionAdmin | None = None) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_AUTEUR] = "acheteur"
    if proposition is not None:
        at.session_state[CLE_PROPOSITION_ADMIN] = proposition
    return at.run()


def _liste_tables(at: AppTest):
    return next(s for s in at.selectbox if s.label == "Table")


def test_liste_a_libelles_lisibles(fabrique):
    at = _connecte()

    assert not at.exception, [e.value for e in at.exception]
    liste = _liste_tables(at)
    assert "Matières" in liste.options
    assert "matieres" not in liste.options
    assert all("historique" not in o.lower() for o in liste.options)


def test_prix_actuel_de_la_matiere_visible(fabrique):
    at = _connecte()
    _liste_tables(at).select("matieres").run()

    assert not at.exception, [e.value for e in at.exception]
    df = at.dataframe[0].value
    assert list(df.columns) == [
        "id",
        "famille",
        "nuance",
        "norme",
        "densite_kg_dm3",
        "prix_eur_kg",
        "fournisseur",
    ]
    s235 = df[df["id"] == "S235JR"].iloc[0]
    assert s235["prix_eur_kg"] == "1.10"


def test_table_vide_message_informatif(fabrique):
    with fabrique() as session:
        session.query(BorneControle).delete()
        session.commit()
    at = _connecte()
    _liste_tables(at).select("bornes_controle").run()

    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    assert any("Aucune ligne" in i.value for i in at.info)


def test_consultable_pendant_une_proposition(fabrique):
    proposition = PropositionAdmin(
        modifications=[
            ModificationAdmin(
                type="mise_a_jour",
                table="matieres",
                ligne_id="S235JR",
                champ="prix_eur_kg",
                valeur=1.25,
            )
        ]
    )
    at = _connecte(proposition)
    _liste_tables(at).select("postes").run()

    assert not at.exception, [e.value for e in at.exception]
    # La proposition reste affichée…
    assert any(b.label == "✅ Accepter et appliquer" for b in at.button)
    # …et la consultation montre les postes (2e tableau, après l'avant/après).
    postes = at.dataframe[1].value
    laser = postes[postes["id"] == "LASER_3KW"].iloc[0]
    assert laser["taux_horaire_eur_h"] == "120.00"
