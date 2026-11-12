"""Acceptance #93 : écran admin — avertissement de rechargement, proposition vide.

Parcours réel de l'écran d'administration avec ``streamlit.testing.v1.AppTest``.
La connexion est simulée par ``session_state[CLE_AUTEUR]`` (aucun secret lu) et
la proposition de l'agent est posée en ``session_state`` (aucun appel IA). La
base locale seedée n'est que lue (affichage avant/après) ; les tests qui
cliquent sur « Accepter » écrivent dans une base seedée en mémoire (``fabrique``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from generateur_devis.admin_agent import ModificationAdmin, PropositionAdmin
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, Matiere, Parametre
from generateur_devis.ui import admin as admin_module
from generateur_devis.ui.admin import CLE_AUTEUR, CLE_PROPOSITION_ADMIN


@pytest.fixture
def fabrique(monkeypatch):
    """Base seedée en mémoire : les tests qui acceptent n'écrivent pas dans data/."""
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


def _ecran(proposition: PropositionAdmin | None) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_AUTEUR] = "methodes"
    if proposition is not None:
        at.session_state[CLE_PROPOSITION_ADMIN] = proposition
    return at.run()


def _libelles(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


def _avertissements(at: AppTest) -> list[str]:
    return [c.value for c in at.caption if "Ne rechargez pas la page" in c.value]


def test_proposition_vide_affiche_la_remarque_et_un_seul_retour():
    remarque = "La table historique_devis n'est pas administrable : rien proposé."
    at = _ecran(PropositionAdmin(modifications=[], remarque=remarque))

    assert not at.exception, [e.value for e in at.exception]
    assert any(remarque in i.value for i in at.info), [i.value for i in at.info]
    libelles = _libelles(at)
    assert "✅ Accepter et appliquer" not in libelles
    assert "❌ Refuser" not in libelles
    assert "Nouvelle demande" in libelles
    # Pas de tableau avant/après vide : seul l'historique (comme sur la saisie).
    assert len(at.dataframe) == len(_ecran(None).dataframe)
    assert _avertissements(at) == []  # rien à perdre

    next(b for b in at.button if b.label == "Nouvelle demande").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert CLE_PROPOSITION_ADMIN not in at.session_state
    assert "Proposer la modification" in _libelles(at)


def test_proposition_vide_sans_remarque_message_de_repli():
    at = _ecran(PropositionAdmin(modifications=[], remarque=None))

    assert not at.exception, [e.value for e in at.exception]
    infos = [i.value for i in at.info]
    assert any("aucune modification" in i for i in infos), infos
    assert "✅ Accepter et appliquer" not in _libelles(at)


def test_proposition_applicable_avertit_de_ne_pas_recharger():
    proposition = PropositionAdmin(
        modifications=[
            ModificationAdmin(
                type="mise_a_jour",
                table="parametres",
                ligne_id="marge_defaut",
                champ="valeur",
                valeur="0.3",
                justification="Marge par défaut portée à 30 %.",
            )
        ]
    )
    at = _ecran(proposition)

    assert not at.exception, [e.value for e in at.exception]
    assert len(_avertissements(at)) == 1
    libelles = _libelles(at)
    assert "✅ Accepter et appliquer" in libelles
    assert "❌ Refuser" in libelles
    assert "Nouvelle demande" not in libelles


def test_saisie_sans_proposition_pas_d_avertissement():
    at = _ecran(None)

    assert not at.exception, [e.value for e in at.exception]
    assert "Proposer la modification" in _libelles(at)
    assert _avertissements(at) == []


def _accepter(proposition: PropositionAdmin) -> AppTest:
    at = _ecran(proposition)
    assert not at.exception, [e.value for e in at.exception]
    next(b for b in at.button if b.label == "✅ Accepter et appliquer").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_message_de_succes_survit_au_rerun(fabrique):
    """Défaut voisin : le ``st.rerun()`` après application effaçait le message."""
    at = _accepter(
        PropositionAdmin(
            modifications=[
                ModificationAdmin(
                    type="mise_a_jour",
                    table="parametres",
                    ligne_id="marge_defaut",
                    champ="valeur",
                    valeur="0.3",
                    justification="30 %",
                )
            ]
        )
    )

    succes = [s.value for s in at.success]
    assert any("1 modification(s) appliquée(s)" in s for s in succes), succes
    assert "Proposer la modification" in _libelles(at)
    with fabrique() as session:
        assert float(session.get(Parametre, "marge_defaut").valeur) == 0.3
    # Affiché une seule fois : le rerun suivant ne le répète pas.
    at.run()
    assert list(at.success) == []


def test_refus_a_l_application_reste_affiche(fabrique):
    """Une re-validation qui échoue à l'acceptation n'est plus effacée en silence."""
    with fabrique() as session:
        prix_avant = session.get(Matiere, "S235JR").prix_eur_kg
    at = _accepter(
        PropositionAdmin(
            modifications=[
                ModificationAdmin(
                    type="mise_a_jour",
                    table="matieres",
                    ligne_id="S235JR",
                    champ="prix_eur_kg",
                    valeur=-1.0,
                    justification="prix négatif",
                )
            ]
        )
    )

    erreurs = [e.value for e in at.error]
    assert any("refusée à l'application" in e for e in erreurs), erreurs
    with fabrique() as session:
        assert session.get(Matiere, "S235JR").prix_eur_kg == prix_avant
