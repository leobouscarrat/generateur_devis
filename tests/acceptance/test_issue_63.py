"""Acceptance #63 : fichier vide ou illisible → message clair, pas de traceback.

Parcours réel de l'écran de dépôt avec ``streamlit.testing.v1.AppTest`` :
dépôt du fichier, clic sur « Lancer l'analyse ». Le vrai ``charger_plan``
tourne ; ``extraire`` / ``creer_modele`` lèvent s'ils sont appelés (aucun appel
au modèle attendu). Aucune écriture en base : la base locale seedée
(``data/devis.db``, via ``get_session``) n'est que lue, comme dans
``test_issue_58.py``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from generateur_devis.ui import pipeline
from generateur_devis.ui.app import CLE_RESULTAT

MESSAGE = "Fichier illisible ou vide : déposez un PDF ou une image de plan."
RACINE = Path(__file__).resolve().parents[2]


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _interdit(*args, **kwargs):
    raise AssertionError("modèle appelé")


def _textes(at: AppTest) -> list[str]:
    return [
        e.value
        for e in (*at.error, *at.warning, *at.info, *at.markdown, *at.caption, *at.exception)
    ]


@pytest.mark.parametrize(
    "fichier",
    [
        ("vide.pdf", b"", "application/pdf"),
        ("faux.pdf", b"hello world", "application/pdf"),
    ],
)
def test_depot_fichier_illisible_reste_sur_le_depot(monkeypatch, fichier):
    monkeypatch.setattr(pipeline, "extraire", _interdit)
    monkeypatch.setattr(pipeline, "creer_modele", _interdit)

    at = AppTest.from_function(_app, default_timeout=30).run()
    at.file_uploader[0].set_value(fichier).run()
    next(b for b in at.button if b.label == "Lancer l'analyse").click().run()

    assert not at.exception, [e.value for e in at.exception]
    # Toujours sur le dépôt, formulaire complet, pas de passage à la validation.
    assert at.title[0].value == "Nouveau devis — dépôt du plan"
    assert MESSAGE in [e.value for e in at.error]
    assert CLE_RESULTAT not in at.session_state
    assert any(b.label == "Lancer l'analyse" for b in at.button)
    assert len(at.file_uploader) == 1
    for texte in _textes(at):
        assert "/tmp" not in texte and ".hermes" not in texte and "Traceback" not in texte


def test_depot_extraction_impossible_reste_sur_le_depot(monkeypatch):
    """PDF valide mais le modèle ne rend aucune pièce : on reste aussi sur le dépôt."""
    import pymupdf

    from generateur_devis.extraction import ResultatExtraction

    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "SUPPORT")
        contenu = doc.tobytes()

    monkeypatch.setattr(
        pipeline,
        "extraire",
        lambda document, modele, **kw: ResultatExtraction("test:m", "test", None, "JSON invalide"),
    )
    monkeypatch.setattr(pipeline, "creer_modele", lambda nom: object())

    at = AppTest.from_function(_app, default_timeout=30).run()
    at.file_uploader[0].set_value(("plan.pdf", contenu, "application/pdf")).run()
    next(b for b in at.button if b.label == "Lancer l'analyse").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Nouveau devis — dépôt du plan"
    assert "Extraction impossible : JSON invalide" in [e.value for e in at.error]
    assert CLE_RESULTAT not in at.session_state


def test_config_streamlit_masque_les_tracebacks():
    config = tomllib.loads((RACINE / ".streamlit" / "config.toml").read_text())
    assert config["client"]["showErrorDetails"] == "none"
