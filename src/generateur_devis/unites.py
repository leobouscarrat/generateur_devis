"""Conversion en mm des pièces lues sur un plan coté en pouces (issue #57).

L'IA recopie les valeurs dans l'unité du plan (convention de ``schema/piece.py``,
règle 2 des ``CONSIGNES``) : la conversion revient au code. Elle est faite par le
pipeline du devis juste après l'extraction, **jamais dans** ``extraire()`` —
l'évaluation compare la sortie brute aux vérités terrain, dans l'unité du plan.

Module pur (ni Streamlit ni base). Chaque valeur convertie est tracée ; une
unité non lue ne déclenche aucune conversion, mais une alerte à l'écran.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Cote,
    Encombrement,
    EtatSurface,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Soudure,
    ToleranceGeometrique,
    Trou,
    Unite,
)

MM_PAR_POUCE = 25.4
"""Définition exacte du pouce (1 in = 25,4 mm). C'est une constante physique, pas une
donnée métier : elle n'a pas sa place en base (le principe « aucune valeur en dur » vise
les données administrables)."""

LONGUEURS: dict[type[BaseModel], tuple[str, ...]] = {
    Matiere: ("epaisseur",),
    Encombrement: ("longueur", "largeur", "hauteur"),
    Aile: ("longueur",),
    Pli: ("rayon_interieur",),
    ProfilPliage: ("rayon_pliage_general",),
    Trou: ("diametre", "longueur", "largeur"),
    CoinCoupe: ("cote1", "cote2", "rayon"),
    Soudure: ("longueur", "gorge"),
    Cote: ("valeur",),  # sauf type == "angle"
    ToleranceGeometrique: ("valeur",),  # largeur de zone : une longueur
}
"""Champs de longueur convertis (× MM_PAR_POUCE) : ``float``, ``float | None`` ou
``Champ[float]`` (on convertit alors ``.valeur``)."""

NON_LONGUEURS: dict[type[BaseModel], tuple[str, ...]] = {
    Pli: ("angle",),
    EtatSurface: ("valeur",),  # rugosité : unité propre (µm, µin, RMS), le texte fait foi
}
"""Champs flottants volontairement non convertis. Seul le test garde-fou s'en sert.
Les champs `confiance` (présents sur tous les modèles) sont exclus par leur nom.
Les quantités (int) et Source.zone (tuple) ne sont pas des champs flottants simples."""


class ValeurConvertie(BaseModel):
    """Trace d'une valeur convertie."""

    model_config = ConfigDict(extra="forbid")

    chemin: str
    """Ex. ``matiere.epaisseur.valeur``, ``contours.trous[0].diametre``."""
    valeur_origine: float
    """Telle que lue sur le plan (in)."""
    valeur_mm: float
    """valeur_origine × MM_PAR_POUCE, stockée exacte (pas d'arrondi)."""


class ConversionUnites(BaseModel):
    """Unité d'origine du plan et valeurs converties."""

    model_config = ConfigDict(extra="forbid")

    unite_origine: Unite | None
    """None = unité non lue sur le plan."""
    valeurs: list[ValeurConvertie] = []


def _a_convertir(modele: BaseModel, nom: str) -> bool:
    if nom not in LONGUEURS.get(type(modele), ()):
        return False
    return not (isinstance(modele, Cote) and modele.type == "angle")


def _convertir(modele: BaseModel, prefixe: str, trace: list[ValeurConvertie]) -> None:
    """Convertit en place (sur une copie) les longueurs de ``modele`` et de ses sous-modèles."""
    for nom in type(modele).model_fields:
        valeur = getattr(modele, nom)
        chemin = f"{prefixe}.{nom}" if prefixe else nom
        if _a_convertir(modele, nom):
            if isinstance(valeur, Champ):
                if valeur.valeur is not None:
                    valeur_mm = valeur.valeur * MM_PAR_POUCE
                    trace.append(
                        ValeurConvertie(
                            chemin=f"{chemin}.valeur",
                            valeur_origine=valeur.valeur,
                            valeur_mm=valeur_mm,
                        )
                    )
                    valeur.valeur = valeur_mm
            elif valeur is not None:
                valeur_mm = valeur * MM_PAR_POUCE
                trace.append(
                    ValeurConvertie(chemin=chemin, valeur_origine=valeur, valeur_mm=valeur_mm)
                )
                setattr(modele, nom, valeur_mm)
        elif isinstance(valeur, BaseModel):
            _convertir(valeur, chemin, trace)
        elif isinstance(valeur, list):
            for i, element in enumerate(valeur):
                if isinstance(element, BaseModel):
                    _convertir(element, f"{chemin}[{i}]", trace)


def convertir_en_mm(piece: PieceExtraite) -> tuple[PieceExtraite, ConversionUnites]:
    """Copie de la pièce avec toutes ses longueurs en mm, et la trace de la conversion.

    - unites == "in" : chaque champ de LONGUEURS non None est multiplié par
      MM_PAR_POUCE (parcours générique des sous-modèles, Champ[float] → .valeur),
      puis ``unites.valeur = "mm"``. confiance et source sont conservées ;
    - unites == "mm" : pièce rendue égale (==), valeurs = [] ;
    - unites null : pièce rendue égale (==), unite_origine = None, rien n'est
      converti (alerte gérée par ``message_unites``).

    La pièce d'entrée n'est jamais modifiée. Idempotente : sur sa propre sortie
    (unites = "mm"), elle ne convertit rien.
    """
    copie = piece.model_copy(deep=True)
    unite = piece.unites.valeur
    conversion = ConversionUnites(unite_origine=unite)
    if unite != "in":
        return copie, conversion
    _convertir(copie, "", conversion.valeurs)
    copie.unites.valeur = "mm"
    return copie, conversion


def valeur_origine(
    conversion: ConversionUnites | None, chemin: str, valeur_mm: float | None
) -> float | None:
    """Valeur lue en pouces pour ce chemin, seulement si la valeur actuelle est encore
    celle issue de la conversion (une valeur modifiée ensuite par l'assistant n'est
    plus « lue sur le plan »)."""
    if conversion is None or valeur_mm is None:
        return None
    for trace in conversion.valeurs:
        if trace.chemin == chemin:
            return trace.valeur_origine if math.isclose(trace.valeur_mm, valeur_mm) else None
    return None


def message_unites(conversion: ConversionUnites) -> tuple[Literal["info", "alerte"], str]:
    """Message d'écran sur l'unité du plan (info, ou alerte si l'unité n'a pas été lue)."""
    if conversion.unite_origine == "in":
        n = len(conversion.valeurs)
        valeurs = "valeur convertie" if n == 1 else "valeurs converties"
        return "info", f"Plan coté en pouces : {n} {valeurs} en mm (× 25,4) par le code."
    if conversion.unite_origine == "mm":
        return "info", "Plan coté en mm."
    return "alerte", "Unité non lue sur le plan : les cotes sont prises en mm, à vérifier."
