"""Interface commune à tous les fournisseurs de modèles capables de lire des images.

Chaque fournisseur (Claude Code, OpenRouter, Nous Research…) implémente `ModeleVision`.
Le reste du code (extraction, évaluation) ne dépend que de cette interface : changer de
fournisseur ne change rien ailleurs.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Image:
    donnees: bytes
    type_mime: str = "image/png"


@dataclass
class ReponseModele:
    texte: str
    modele: str
    duree_s: float
    cout_usd: float | None = None
    tokens_entree: int | None = None
    tokens_sortie: int | None = None
    brut: dict[str, Any] = field(default_factory=dict)


class ErreurModele(RuntimeError):
    """Échec d'un appel (réseau, quota, réponse vide…)."""


class ModeleVision(Protocol):
    nom: str
    """Identifiant stable, ex. « claude-code:sonnet ». Sert de clé de cache."""

    def generer(
        self, prompt_systeme: str, prompt_utilisateur: str, images: list[Image]
    ) -> ReponseModele: ...
