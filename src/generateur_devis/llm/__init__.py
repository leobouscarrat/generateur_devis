"""Accès aux modèles d'IA capables de lire des images.

Un modèle est désigné par « fournisseur:modèle », par exemple :
- claude-code:sonnet            (abonnement Claude, via Claude Code)
- openrouter:google/gemini-flash (OpenRouter, clé OPENROUTER_API_KEY)
- nous:<modèle>                 (Nous Research, clé NOUS_API_KEY)
"""

import os

from dotenv import find_dotenv, load_dotenv

from generateur_devis.llm.base import ErreurModele, Image, ModeleVision, ReponseModele
from generateur_devis.llm.claude_code import ClaudeCode
from generateur_devis.llm.openai_compatible import OpenAICompatible

URL_OPENROUTER = "https://openrouter.ai/api/v1"
URL_NOUS = "https://inference-api.nousresearch.com/v1"  # à vérifier avec le compte Nous Research

FOURNISSEURS: tuple[str, ...] = ("claude-code", "openrouter", "nous")
"""Fournisseurs reconnus par `creer_modele` (un cas par fournisseur ci-dessous)."""

MODELE_MAL_CONFIGURE = (
    "Modèle d'IA mal configuré (paramètre « modele_extraction » ou variable MODELE_EXTRACTION)"
)
"""Préfixe des messages d'erreur quand la désignation configurée est invalide."""


def verifier_designation(designation: str) -> tuple[str, str]:
    """Découpe une désignation « fournisseur:modèle » et vérifie son format.

    Règle unique, appliquée par `creer_modele` et par l'agent admin (paramètre
    ``modele_extraction``, issue #92). Pure : ni réseau, ni ``.env``, ni
    construction du client — la clé d'API et l'exécutable ne sont pas vérifiés.

    Returns:
        Le couple (fournisseur, modèle).

    Raises:
        ValueError: modèle vide (pas de « : » ou rien après) ou fournisseur
            hors `FOURNISSEURS`.
    """
    fournisseur, _, modele = designation.partition(":")
    if not modele:
        raise ValueError(f"Format attendu « fournisseur:modèle », reçu « {designation} »")
    if fournisseur not in FOURNISSEURS:
        raise ValueError(f"Fournisseur inconnu : {fournisseur}")
    return fournisseur, modele


def creer_modele(designation: str) -> ModeleVision:
    fournisseur, modele = verifier_designation(designation)
    load_dotenv(find_dotenv(usecwd=True))
    if fournisseur == "claude-code":
        return ClaudeCode(modele=modele)
    if fournisseur == "openrouter":
        return OpenAICompatible(
            "openrouter",
            URL_OPENROUTER,
            os.environ.get("OPENROUTER_API_KEY", ""),
            modele,
            options={"usage": {"include": True}},  # renvoie le coût réel de l'appel
        )
    return OpenAICompatible("nous", URL_NOUS, os.environ.get("NOUS_API_KEY", ""), modele)


__all__ = [
    "FOURNISSEURS",
    "MODELE_MAL_CONFIGURE",
    "ErreurModele",
    "Image",
    "ModeleVision",
    "ReponseModele",
    "creer_modele",
    "verifier_designation",
]
