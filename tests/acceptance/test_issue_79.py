"""Acceptance #79 : plus de champ « Modèle de l'agent » ni de traceback.

Parcours réel de l'écran d'administration avec ``streamlit.testing.v1.AppTest``.
La connexion est simulée par ``session_state[CLE_AUTEUR]`` (aucun secret lu).
Le modèle vient de ``MODELE_EXTRACTION`` (sinon du paramètre ``modele_extraction``) :
une désignation invalide doit produire un message clair. Le vrai ``creer_modele``
lève avant tout appel réseau ; la base locale seedée n'est que lue.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.ui.admin import CLE_AUTEUR


def _app() -> None:
    from generateur_devis.ui.admin import main

    main()


def _connecte() -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_AUTEUR] = "methodes"
    return at.run()


def test_pas_de_champ_modele_dans_l_ecran_admin():
    at = _connecte()

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Administration des référentiels"
    assert all(t.label != "Modèle de l'agent" for t in at.text_input)


def test_modele_invalide_message_clair_sans_traceback(monkeypatch):
    monkeypatch.setenv("MODELE_EXTRACTION", "modele-qui-nexiste-pas")
    at = _connecte()

    at.text_area[0].input("le S235JR passe à 1,25 €/kg").run()
    bouton = next(b for b in at.button if b.label == "Proposer la modification")
    assert not bouton.disabled
    bouton.click().run()

    assert not at.exception, [e.value for e in at.exception]
    erreurs = [e.value for e in at.error]
    assert len(erreurs) == 1, erreurs
    assert "Modèle d'IA mal configuré" in erreurs[0]
    assert "fournisseur:modèle" in erreurs[0]
    assert ".py" not in erreurs[0]
    # On reste sur la saisie : aucune proposition affichée.
    assert any(b.label == "Proposer la modification" for b in at.button)
