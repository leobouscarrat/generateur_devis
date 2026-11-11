"""Tests de la connexion de démonstration de l'administration (issue #38)."""

from generateur_devis.ui.auth import verifier_identifiants

COMPTES = {"acheteur": "prix2026", "methodes": "temps2026", "direction": "pilotage2026"}


def test_identifiants_corrects():
    assert verifier_identifiants("acheteur", "prix2026", COMPTES)


def test_mot_de_passe_incorrect():
    assert not verifier_identifiants("acheteur", "mauvais", COMPTES)


def test_utilisateur_inconnu():
    assert not verifier_identifiants("intrus", "prix2026", COMPTES)


def test_sensible_a_la_casse():
    assert not verifier_identifiants("acheteur", "PRIX2026", COMPTES)
