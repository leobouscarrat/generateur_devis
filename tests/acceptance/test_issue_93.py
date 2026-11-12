"""Acceptance #93 : écran admin — avertissement de rechargement, proposition vide.

Parcours réel de l'écran d'administration avec ``streamlit.testing.v1.AppTest``.
La connexion est simulée par ``session_state[CLE_AUTEUR]`` (aucun secret lu) et
la proposition de l'agent est posée en ``session_state`` (aucun appel IA). La
base locale seedée n'est que lue (affichage avant/après) : aucun clic sur
« Accepter », donc aucune écriture.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.admin_agent import ModificationAdmin, PropositionAdmin
from generateur_devis.ui.admin import CLE_AUTEUR, CLE_PROPOSITION_ADMIN


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
