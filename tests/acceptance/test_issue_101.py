"""Acceptance #101 : aucun texte de développement affiché par le mode « magic » de Streamlit.

`streamlit run` exécute le module de l'écran comme script : toute chaîne isolée
(docstring d'attribut, par exemple) est affichée à l'écran. On rejoue donc le
**vrai script** avec ``AppTest.from_file``, et non ``from_function``, qui
n'exécute que ``main()``.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RACINE = Path(__file__).resolve().parents[2]
ECRANS = [
    RACINE / "src/generateur_devis/ui/app.py",
    RACINE / "src/generateur_devis/ui/admin.py",
]


def test_ecran_devis_sans_docstring_affichee():
    at = AppTest.from_file(str(ECRANS[0]), default_timeout=30).run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Nouveau devis — dépôt du plan"
    textes = [m.value for m in at.markdown]
    assert not any("Libellé affiché" in t for t in textes), textes


def test_magic_desactive():
    """Garde de classe : même une future chaîne isolée ne s'afficherait pas."""
    config = tomllib.loads((RACINE / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["runner"]["magicEnabled"] is False


@pytest.mark.parametrize("ecran", ECRANS, ids=lambda p: p.name)
def test_aucune_chaine_isolee_au_niveau_module(ecran):
    """Hors docstring du module, aucune chaîne isolée au niveau module d'un écran."""
    arbre = ast.parse(ecran.read_text(encoding="utf-8"))
    isolees = [
        noeud.lineno
        for noeud in arbre.body[1:]
        if isinstance(noeud, ast.Expr)
        and isinstance(noeud.value, ast.Constant)
        and isinstance(noeud.value.value, str)
    ]
    assert isolees == [], f"chaînes isolées lignes {isolees}"
