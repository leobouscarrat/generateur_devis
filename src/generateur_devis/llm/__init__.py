"""Accès aux modèles d'IA capables de lire des images.

Un modèle est désigné par « fournisseur:modèle », par exemple :
- claude-code:sonnet            (abonnement Claude, via Claude Code)
- openrouter:google/gemini-flash (OpenRouter, clé OPENROUTER_API_KEY)
- nous:<modèle>                 (Nous Research, clé NOUS_API_KEY)
"""

import os

from dotenv import load_dotenv

from generateur_devis.llm.base import ErreurModele, Image, ModeleVision, ReponseModele
from generateur_devis.llm.claude_code import ClaudeCode
from generateur_devis.llm.openai_compatible import OpenAICompatible

URL_OPENROUTER = "https://openrouter.ai/api/v1"
URL_NOUS = "https://inference-api.nousresearch.com/v1"  # à vérifier avec le compte Nous Research


def creer_modele(designation: str) -> ModeleVision:
    load_dotenv()
    fournisseur, _, modele = designation.partition(":")
    if not modele:
        raise ValueError(f"Format attendu « fournisseur:modèle », reçu « {designation} »")
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
    if fournisseur == "nous":
        return OpenAICompatible("nous", URL_NOUS, os.environ.get("NOUS_API_KEY", ""), modele)
    raise ValueError(f"Fournisseur inconnu : {fournisseur}")


__all__ = ["ErreurModele", "Image", "ModeleVision", "ReponseModele", "creer_modele"]
