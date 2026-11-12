"""Acceptance #99 : outils en ligne de commande, modèle mal configuré → message clair.

Les deux CLI (`generateur_devis.extraction`, `etude_extraction`) valident
``--modele`` par la règle unique `verifier_designation` (#92) et construisent le
modèle **avant** de charger le plan / le jeu : aucune erreur ne sort en
traceback, le code de sortie est celui d'argparse (2).
"""

from __future__ import annotations

import pytest

import etude_extraction.__main__ as cli_etude
import generateur_devis.extraction.__main__ as cli_extraction


def _interdit(*args, **kwargs):
    raise AssertionError("chargement du plan/jeu avant la validation du modèle")


@pytest.fixture
def sans_cle_openrouter(monkeypatch):
    """`.env` neutralisé et clé retirée : `creer_modele` lève ErreurModele sans réseau."""
    monkeypatch.setattr("generateur_devis.llm.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def _lancer(monkeypatch, capsys, main, argv: list[str]) -> str:
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as sortie:
        main()
    assert sortie.value.code == 2
    return capsys.readouterr().err


@pytest.mark.parametrize("designation", ["sonnet", "inconnu:modele", "openrouter:"])
def test_extraction_designation_invalide(monkeypatch, capsys, designation):
    monkeypatch.setattr(cli_extraction, "charger_plan", _interdit)
    err = _lancer(
        monkeypatch, capsys, cli_extraction.main, ["prog", "plan.pdf", "--modele", designation]
    )
    assert "--modele" in err
    assert "Traceback" not in err


def test_extraction_modele_indisponible(monkeypatch, capsys, sans_cle_openrouter):
    monkeypatch.setattr(cli_extraction, "charger_plan", _interdit)
    err = _lancer(
        monkeypatch,
        capsys,
        cli_extraction.main,
        ["prog", "plan.pdf", "--modele", "openrouter:google/gemini-2.5-flash"],
    )
    assert "Modèle d'IA indisponible" in err
    assert "clé d'API manquante" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("designation", ["sonnet", "inconnu:modele"])
def test_etude_designation_invalide(monkeypatch, capsys, designation):
    monkeypatch.setattr(cli_etude, "charger_jeu", _interdit)
    err = _lancer(
        monkeypatch, capsys, cli_etude.main, ["prog", "--jeu", "ecado", "--modele", designation]
    )
    assert "--modele" in err
    assert "Traceback" not in err


def test_etude_modele_indisponible(monkeypatch, capsys, sans_cle_openrouter):
    monkeypatch.setattr(cli_etude, "charger_jeu", _interdit)
    err = _lancer(
        monkeypatch,
        capsys,
        cli_etude.main,
        ["prog", "--jeu", "ecado", "--modele", "openrouter:google/gemini-2.5-flash:free"],
    )
    assert "Modèle d'IA indisponible" in err
    assert "Traceback" not in err
