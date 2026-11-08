"""Tests de l'extraction sans appel réel à un modèle (modèle factice)."""

from pathlib import Path

import pytest

from generateur_devis.extraction.documents import Plan
from generateur_devis.extraction.extracteur import extraire, extraire_json
from generateur_devis.llm.base import ErreurModele, Image, ReponseModele
from generateur_devis.llm.claude_code import trouver_executable

EXEMPLE = (Path(__file__).resolve().parents[1] / "exemples" / "equerre_fictive.json").read_text(
    encoding="utf-8"
)
PLAN = Plan(Path("plan.png"), [Image(b"fausse image")], "")


class ModeleFactice:
    """Renvoie les réponses prévues, dans l'ordre, et compte les appels."""

    def __init__(self, reponses: list[str | Exception], nom: str = "factice:test"):
        self.reponses = list(reponses)
        self.nom = nom
        self.appels: list[str] = []

    def generer(self, prompt_systeme, prompt_utilisateur, images):
        self.appels.append(prompt_utilisateur)
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return ReponseModele(texte=reponse, modele=self.nom, duree_s=0.1, cout_usd=0.01)


def test_extraire_json_avec_balises():
    texte = 'Voici la fiche :\n```json\n{"a": {"b": 1}}\n```\nBonne journée'
    assert extraire_json(texte) == '{"a": {"b": 1}}'


def test_extraire_json_absent():
    with pytest.raises(ValueError):
        extraire_json("pas de JSON ici")


def test_reponse_valide_du_premier_coup():
    modele = ModeleFactice([EXEMPLE])
    resultat = extraire(PLAN, modele, dossier_cache=None)
    assert resultat.piece is not None and resultat.erreur is None
    assert len(modele.appels) == 1
    assert resultat.cout_usd == pytest.approx(0.01)


def test_correction_apres_reponse_invalide():
    modele = ModeleFactice(['{"champ_invente": 1}', EXEMPLE])
    resultat = extraire(PLAN, modele, dossier_cache=None)
    assert resultat.piece is not None
    assert len(modele.appels) == 2
    assert "Erreurs de validation" in modele.appels[1]


def test_echec_apres_toutes_les_tentatives():
    modele = ModeleFactice(["n'importe quoi", "toujours pas"])
    resultat = extraire(PLAN, modele, dossier_cache=None)
    assert resultat.piece is None and resultat.erreur


def test_erreur_d_acces_non_mise_en_cache(tmp_path):
    modele = ModeleFactice([ErreurModele("quota dépassé")])
    resultat = extraire(PLAN, modele, dossier_cache=tmp_path)
    assert resultat.erreur == "quota dépassé"
    assert list(tmp_path.iterdir()) == []


def test_cache_evite_un_second_appel(tmp_path):
    premier = ModeleFactice([EXEMPLE])
    extraire(PLAN, premier, dossier_cache=tmp_path)
    second = ModeleFactice([])  # aucun appel autorisé
    resultat = extraire(PLAN, second, dossier_cache=tmp_path)
    assert resultat.depuis_cache and resultat.piece is not None
    assert second.appels == []


def test_executable_claude_depuis_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_BIN", "/chemin/vers/claude")
    assert trouver_executable() == "/chemin/vers/claude"
