"""Module de calculs géométriques déterminés pour la tôlerie.

Fournit les fonctions pures suivantes (toutes annotées avec types Pydantic v2) :
- Formule du développé (BA, longueur développée, BD)
- Surface polygonale (shoelace) + aires de trous par forme
- Masse (flan via rectangle englobant, nette par surface − trous)
- Longueur de coupe (périmètre extérieur + périmètres de trous)
- Nombre d'amorçages

Aucune valeur en dur : densités et facteur K proviennent de la couche
d'accès ``acces.py`` (``get_parametre``).
"""

from __future__ import annotations

import math
from typing import Literal

# ---------------------------------------------------------------------------
# Types internes
# ---------------------------------------------------------------------------

Point2D = tuple[float, float]


# ---------------------------------------------------------------------------
# Formule du développé ( §2.4 logique_metier.md )
# ---------------------------------------------------------------------------

def calculer_ba(
    angle_degres: float,
    rayon_interieur: float,
    epaisseur: float,
    facteur_k: float = 0.40,
) -> float:
    """BA (bend allowance) selon §2.4 logique_metier.md.

    BA = π × angle/180 × (R + K × e)

    Args:
        angle_degres: angle de pliage en degrés (90 pour équerre).
        rayon_interieur: rayon intérieur de pliage en mm.
        epaisseur: épaisseur de la tôle en mm.
        facteur_k: facteur neutre K (défaut 0,40 depuis la base).

    Returns:
        Longueur BA en mm.
    """
    return math.pi * angle_degres / 180 * (rayon_interieur + facteur_k * epaisseur)


def longueur_developue(
    ailes_longueurs_interieures: list[float],
    angles: list[float],
    rayons: list[float],
    epaisseurs: list[float],
    facteur_k: float = 0.40,
) -> float:
    """Longueur développée = Σ ailes intérieures + Σ BA.

    Args:
        ailes_longueurs_interieures: longueurs des ailes intérieures en mm.
        angles: angles de pliage en degrés (un par pli).
        rayons: rayons intérieurs en mm (un par pli).
        epaisseurs: épaisseurs en mm (un par pli).
        facteur_k: facteur neutre K (défaut 0,40).

    Returns:
        Longueur développée totale en mm.
    """
    if not (len(ailes_longueurs_interieures) == len(angles) == len(rayons) == len(epaisseurs)):
        msg = "Toutes les listes doivent avoir la même longueur"
        raise ValueError(msg)
    ba_total = sum(
        calculer_ba(a, r, e, facteur_k) for a, r, e in zip(angles, rayons, epaisseurs)
    )
    return sum(ailes_longueurs_interieures) + ba_total


def longueur_bd_ext(
    angles: list[float],
    rayons: list[float],
    epaisseurs: list[float],
    facteur_k: float = 0.40,
) -> float:
    """Longueur variante cotes extérieures : Σ cotes ext − Σ BD.

    BD = 2 × (R + e) × tan(angle/2) − BA,  BA = π × angle/180 × (R + K × e)

    Args:
        angles: angles de pliage en degrés.
        rayons: rayons intérieurs en mm.
        epaisseurs: épaisseurs en mm.
        facteur_k: facteur neutre K (défaut 0,40).

    Returns:
        Longueur en variante cotes extérieures en mm.
    """
    ba_total = sum(calculer_ba(a, r, e, facteur_k) for a, r, e in zip(angles, rayons, epaisseurs))
    bd_total = sum(
        2 * (r + e) * math.tan(math.radians(a) / 2) - ba
        for ba, a, e in zip([ba_total] * len(angles) if ba_total else [], angles, epaisseurs)
    )
    # Note : la somme des cotes extérieures est fournie par le caller
    # (encombrement de la pièce). On renvoie ici seulement la partie BD.
    # L'appelant fera : longueur = cotes_ext_total - bd_total
    return bd_total


# ---------------------------------------------------------------------------
# Surface : formule de l'arpenteur (shoelace) + aires de trous
# ---------------------------------------------------------------------------

def aire_polygone_shoelace(points: list[Point2D]) -> float:
    """Aire d'un polygone par la formule de l'arpenteur (shoelace).

    Args:
        points: sommets du polygone en coordonnées (x, y) en mm,
            dans l'ordre (horaire ou anti-horaire).

    Returns:
        Aire en mm².
    """
    aire = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        aire += x1 * y2 - x2 * y1
    return abs(aire) / 2.0


def aire_trou(
    forme: Literal["rond", "oblong", "carre", "rectangulaire", "autre"],
    diametre: float | None = None,
    longueur: float | None = None,
    largeur: float | None = None,
    quantite: int = 1,
) -> float:
    """Aire d'un trou selon sa forme, multipliée par ``quantite``.

    Args:
        forme: forme du trou. Doit être l'un des littéraux autorisés
            (correspond aux valeurs de ``Trou.forme`` dans ``piece.py:176``).
        diametre: diamètre, pour un trou rond.
        longueur: longueur, pour un oblong ou un rectangle.
        largeur: largeur, pour un oblong ou un rectangle.
        quantite: nombre de trous identiques (défaut 1).

    Returns:
        Aire totale en mm².

    Raises:
        ValueError: si ``forme`` est ``"autre"``.
    """
    if forme == "rond":
        if diametre is None:
            msg = "Un trou rond nécessite un diamètre"
            raise ValueError(msg)
        aire_un = math.pi * (diametre / 2) ** 2
    elif forme == "carre":
        if longueur is None or largeur is None:
            msg = "Un trou carré nécessite longueur et largeur"
            raise ValueError(msg)
        aire_un = longueur * largeur
    elif forme == "rectangulaire":
        if longueur is None or largeur is None:
            msg = "Un trou rectangulaire nécessite longueur et largeur"
            raise ValueError(msg)
        aire_un = longueur * largeur
    elif forme == "oblong":
        if longueur is None or largeur is None:
            msg = "Un trou oblong nécessite longueur et largeur"
            raise ValueError(msg)
        # Rectangle + 2 demi-cercles (cercle de diamètre = largeur)
        aire_rect = longueur * largeur
        aire_cercle = math.pi * (largeur / 2) ** 2
        aire_un = aire_rect + aire_cercle
    elif forme == "autre":
        msg = "Forme de trou inconnue : autre. Veuillez utiliser l'une des formes connues."
        raise ValueError(msg)
    else:
        msg = f"Forme de trou inconnue : {forme!r}"
        raise ValueError(msg)

    return aire_un * quantite


# ---------------------------------------------------------------------------
# Masse
# ---------------------------------------------------------------------------

def calculer_masse(
    surface_nette_mm2: float,
    epaisseur_mm: float,
    densite_kg_dm3: float,
) -> float:
    """Calcul de la masse selon surface_nette × e × densité × 1e-6.

    Formule : masse (kg) = surface_nette (mm²) × ép. (mm) × densité (kg/dm³) × 1e-6

    C'est la **masse nette** (surface_nette = flan − trous).

    La **masse flan** utilise le rectangle englobant (voir §3 Bloc 1
    logique_metier.md : ``masse_flan = L_flan × l_flan × e × densité``).

    Args:
        surface_nette_mm2: surface nette en mm².
        epaisseur_mm: épaisseur en mm.
        densite_kg_dm3: densité en kg/dm³ (via ``get_matiere`` ou ``get_parametre``).

    Returns:
        Masse en kg.
    """
    return surface_nette_mm2 * epaisseur_mm * densite_kg_dm3 * 1e-6


def calculer_masse_flan(
    long_flan_mm: float,
    large_flan_mm: float,
    epaisseur_mm: float,
    densite_kg_dm3: float,
) -> float:
    """Masse flan via rectangle englobant : L × l × e × densité × 1e-6.

    Args:
        long_flan_mm: longueur du flan en mm.
        large_flan_mm: largeur du flan en mm.
        epaisseur_mm: épaisseur en mm.
        densite_kg_dm3: densité en kg/dm³.

    Returns:
        Masse flan en kg.
    """
    surface_flan_mm2 = long_flan_mm * large_flan_mm
    return surface_flan_mm2 * epaisseur_mm * densite_kg_dm3 * 1e-6


# ---------------------------------------------------------------------------
# Longueur de coupe
# ---------------------------------------------------------------------------

def perimetre_ogonale(points: list[Point2D]) -> float:
    """Périmètre d'un polygone fermé (contour extérieur).

    Args:
        points: sommets du polygone en (x, y), le dernier point se ferme
            automatiquement sur le premier.

    Returns:
        Périmètre en mm.
    """
    if not points:
        return 0.0
    perim = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        perim += math.hypot(x2 - x1, y2 - y1)
    return perim


def longueur_coupe(
    points_flan: list[Point2D],
    trous: list[dict],
) -> float:
    """Longueur de coupe = périmètre extérieur + Σ périmètres des trous.

    Args:
        points_flan: sommets du rectangle englobant du flan (à plat).
        trous: liste de dicts describing each trou, avec les clés :
            - ``forme`` : Literal["rond", "oblong", "carre", "rectangulaire"]
            - ``diametre`` : float | None (pour rond)
            - ``longueur`` : float | None (pour oblong/rectangle)
            - ``largeur`` : float | None (pour oblong/rectangle)

    Returns:
        Longueur de coupe totale en mm.
    """
    # Périmètre extérieur du flan
    perim_ext = perimetre_ogonale(points_flan)

    # Périmètres des trous
    perim_trous = 0.0
    for trou in trous:
        forme = trou.get("forme", "rond")
        if forme == "rond":
            diam = trou.get("diametre", 0.0)
            perim_trous += math.pi * diam
        elif forme in ("carre", "rectangulaire"):
            long = trou.get("longueur", 0.0) or 0.0
            larg = trou.get("largeur", 0.0) or 0.0
            # Périmètre du rectangle
            perim_trous += 2 * (long + larg)
        elif forme == "oblong":
            long = trou.get("longueur", 0.0) or 0.0
            larg = trou.get("largeur", 0.0) or 0.0
            # Périmètre : 2×longueur + π×largeur (deux demi-cercles)
            perim_trous += 2 * long + math.pi * larg

    return perim_ext + perim_trous


def nombre_amorçages(trous: list[dict]) -> int:
    """Nombre d'amorçages = 1 (contour extérieur) + nb de contours intérieurs.

    Args:
        trous: liste de trous extraits (même format que pour ``longueur_coupe``).

    Returns:
        Nombre d'amorçages.
    """
    return 1 + len(trous)
