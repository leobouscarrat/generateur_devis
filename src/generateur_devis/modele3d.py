"""Modèle 3D de la pièce pliée (issue #8).

Construction du solide de validation : la ligne médiane du profil de pliage
(plan de la vue de côté) est extrudée sur la largeur de la pièce pour former
une surface (maillage sommets + faces), affichable en vues dessus / côté au
même cadrage que le plan (docs/architecture.md §3a et §4).

Limites V1 :
- plis tous parallèles (périmètre du schéma ``ProfilPliage``) ;
- les trous et chanfreins ne sont pas retirés du solide : leurs positions ne
  sont pas extraites du plan (même limite que ``geometrie.py``) ;
- les plis sont représentés par des coins vifs (pas d'arc de rayon) : la
  longueur de la ligne médiane reste égale au développé du flan.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from generateur_devis.geometrie import (
    ErreurGeometrie,
    Point2D,
    calculer_ba,
    calculer_bd,
    rayon_pli,
    verifier_alternance,
)
from generateur_devis.schema.piece import Aile, PieceExtraite, Pli
from generateur_devis.ui.formatage import formater_valeur

Point3D = tuple[float, float, float]


class Maillage(BaseModel):
    """Surface de la pièce pliée : sommets 3D et faces (indices de sommets)."""

    model_config = ConfigDict(extra="forbid")

    sommets: list[Point3D]
    """Sommets du maillage, en mm (x = développé, y = largeur, z = élévation)."""
    faces: list[tuple[int, ...]]
    """Faces quadrilatères, indices dans ``sommets``."""
    epaisseur_mm: float
    """Épaisseur de tôle (surface médiane en V1, l'épaisseur n'est pas volumique)."""


def construire_profil_2d(piece: PieceExtraite, facteur_k: float) -> list[Point2D]:
    """Ligne médiane du profil plié, vue de côté : liste de points (x, z) en mm.

    Chaque pli tourne la direction de ± son angle (sens « haut » / « bas » ;
    « inconnu » est traité comme « haut »). La longueur totale de la ligne est
    égale à la longueur développée du flan (``geometrie.longueur_developpee``) :
    chaque extrémité d'aile pliée est raccourcie de BD/2 (cotation extérieure)
    ou allongée de BA/2 (cotation intérieure).

    Raises:
        ErreurGeometrie: profil/cotation/rayon/épaisseur manquants, profil vide
            ou non alterné, ou profil qui se croise (cotes contradictoires).
    """
    profil = piece.profil_pliage
    if profil is None:
        msg = "Profil de pliage absent : impossible de construire le modèle 3D."
        raise ErreurGeometrie(msg)
    verifier_alternance(profil)

    elements = profil.elements
    plis = [e for e in elements if isinstance(e, Pli)]
    if not plis:
        # Pièce plate : une seule aile horizontale.
        aile = elements[0]
        assert isinstance(aile, Aile)
        return [(0.0, 0.0), (aile.longueur, 0.0)]

    if profil.cotation == "inconnue":
        msg = (
            "Cotation du profil inconnue : indiquez si les longueurs d'ailes sont "
            "cotées à l'extérieur ou à l'intérieur des plis."
        )
        raise ErreurGeometrie(msg)

    epaisseur = piece.matiere.epaisseur.valeur
    if epaisseur is None or epaisseur <= 0:
        msg = "Épaisseur de tôle absente ou invalide : impossible de construire le modèle 3D."
        raise ErreurGeometrie(msg)

    rayons = [rayon_pli(p, profil.rayon_pliage_general, i) for i, p in enumerate(plis)]

    def correction(pli_index: int) -> float:
        """Longueur retirée (cotation ext.) ou ajoutée (int.) à chaque extrémité pliée."""
        pli = plis[pli_index]
        if profil.cotation == "exterieure":
            return -calculer_bd(pli.angle, rayons[pli_index], epaisseur, facteur_k) / 2
        return calculer_ba(pli.angle, rayons[pli_index], epaisseur, facteur_k) / 2

    # Longueurs effectives des segments (une par aile) et rotations (une par pli).
    ailes = [e for e in elements if isinstance(e, Aile)]
    longueurs: list[float] = []
    for i, aile in enumerate(ailes):
        longueur = aile.longueur
        if i > 0:
            longueur += correction(i - 1)
        if i < len(plis):
            longueur += correction(i)
        if longueur <= 0:
            adjacents = [rayons[j] for j in (i - 1, i) if 0 <= j < len(plis)]
            rayons_txt = ", ".join(f"{r:g}" for r in dict.fromkeys(adjacents))
            msg = (
                f"Cotes contradictoires : l'aile n°{i + 1} ({aile.longueur:g} mm) est "
                f"trop courte pour ses plis (épaisseur {epaisseur:g} mm, rayon "
                f"{rayons_txt} mm) : il reste {formater_valeur('longueur_mm', longueur)} mm. "
                "Vérifiez l'aile, l'épaisseur et le rayon de pliage."
            )
            raise ErreurGeometrie(msg)
        longueurs.append(longueur)

    # Marche le long du profil : direction initiale +x, rotation ±angle à chaque pli.
    points: list[Point2D] = [(0.0, 0.0)]
    theta = 0.0
    x, z = 0.0, 0.0
    for i, longueur in enumerate(longueurs):
        x += longueur * math.cos(theta)
        z += longueur * math.sin(theta)
        points.append((x, z))
        if i < len(plis):
            sens = -1.0 if plis[i].sens == "bas" else 1.0
            theta += sens * math.radians(plis[i].angle)

    _verifier_auto_intersection(points)
    return points


def _verifier_auto_intersection(points: list[Point2D]) -> None:
    """Erreur si deux segments non consécutifs du profil se croisent."""

    def croise(a1: Point2D, a2: Point2D, b1: Point2D, b2: Point2D) -> bool:
        def orient(o: Point2D, p: Point2D, q: Point2D) -> float:
            return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

        d1 = orient(b1, b2, a1)
        d2 = orient(b1, b2, a2)
        d3 = orient(a1, a2, b1)
        d4 = orient(a1, a2, b2)
        return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)

    segments = list(zip(points, points[1:], strict=False))
    for i, (a1, a2) in enumerate(segments):
        for b1, b2 in segments[i + 2 :]:
            if croise(a1, a2, b1, b2):
                msg = "Cotes contradictoires : le profil plié se croise lui-même."
                raise ErreurGeometrie(msg)


def extruder_profil(profil: list[Point2D], largeur_mm: float, epaisseur_mm: float) -> Maillage:
    """Extrude la ligne de profil (plan x/z) sur la largeur (axe y).

    Deux rangées de sommets (y = 0 et y = largeur), une face quadrilatère par
    segment du profil.
    """
    if largeur_mm <= 0:
        msg = f"Largeur d'extrusion invalide : {largeur_mm} mm."
        raise ErreurGeometrie(msg)
    n = len(profil)
    sommets: list[Point3D] = [(x, 0.0, z) for x, z in profil] + [
        (x, largeur_mm, z) for x, z in profil
    ]
    faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
    return Maillage(sommets=sommets, faces=faces, epaisseur_mm=epaisseur_mm)


def construire_modele_3d(piece: PieceExtraite, facteur_k: float) -> Maillage:
    """Modèle 3D complet : profil 2D extrudé sur la largeur d'encombrement.

    Réutilise les mêmes données d'entrée que ``geometrie.construire_flan`` :
    la largeur vient de ``encombrement.largeur``.

    Raises:
        ErreurGeometrie: mêmes causes que :func:`construire_profil_2d`, ou
            largeur d'encombrement absente/invalide.
    """
    largeur = piece.encombrement.largeur.valeur
    if largeur is None or largeur <= 0:
        msg = "Largeur d'encombrement absente ou invalide : impossible de construire le modèle 3D."
        raise ErreurGeometrie(msg)
    epaisseur = piece.matiere.epaisseur.valeur
    if epaisseur is None or epaisseur <= 0:
        msg = "Épaisseur de tôle absente ou invalide : impossible de construire le modèle 3D."
        raise ErreurGeometrie(msg)
    profil = construire_profil_2d(piece, facteur_k)
    return extruder_profil(profil, largeur, epaisseur)


def longueur_ligne(points: list[Point2D]) -> float:
    """Longueur d'une ligne brisée (invariant : égale au développé du flan)."""
    return sum(
        math.hypot(x2 - x1, z2 - z1) for (x1, z1), (x2, z2) in zip(points, points[1:], strict=False)
    )
