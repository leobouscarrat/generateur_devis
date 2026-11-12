"""Tests de la désignation des modèles d'IA (issue #92).

``verifier_designation`` est la règle de format unique, partagée par
``creer_modele`` et l'agent admin : pure, sans réseau ni ``.env``.
"""

from __future__ import annotations

import pytest

from generateur_devis.llm import FOURNISSEURS, creer_modele, verifier_designation


@pytest.mark.parametrize(
    ("designation", "attendu"),
    [
        ("claude-code:sonnet", ("claude-code", "sonnet")),
        ("openrouter:google/gemini-2.5-flash", ("openrouter", "google/gemini-2.5-flash")),
        ("nous:hermes-4", ("nous", "hermes-4")),
    ],
)
def test_designation_valide(designation, attendu):
    assert verifier_designation(designation) == attendu


@pytest.mark.parametrize(
    ("designation", "message"),
    [
        ("sonnet", "Format attendu « fournisseur:modèle »"),
        ("openrouter:", "Format attendu « fournisseur:modèle »"),
        ("", "Format attendu « fournisseur:modèle »"),
        ("foo:bar", "Fournisseur inconnu : foo"),
    ],
)
def test_designation_invalide(designation, message):
    with pytest.raises(ValueError, match=message):
        verifier_designation(designation)


def test_garde_fou_chaque_fournisseur_connu_est_accepte():
    for fournisseur in FOURNISSEURS:
        assert verifier_designation(f"{fournisseur}:m") == (fournisseur, "m")


def test_creer_modele_applique_la_meme_regle(monkeypatch):
    """``creer_modele`` refuse avant toute construction (ni .env ni réseau)."""
    monkeypatch.setattr("generateur_devis.llm.load_dotenv", lambda *a, **k: None)
    with pytest.raises(ValueError, match="Fournisseur inconnu : foo"):
        creer_modele("foo:bar")
    with pytest.raises(ValueError, match="Format attendu"):
        creer_modele("sonnet")
