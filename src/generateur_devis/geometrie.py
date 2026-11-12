"""Géométrie déterministe de la tôlerie : pièce à plat et mesures (issue #7).

À partir d'une pièce extraite (``schema/piece.py``), ce module construit le flan
(la pièce à plat, avant pliage) et calcule les mesures utilisées par le chiffrage :
développé, surfaces, masses, longueur de coupe et nombre d'amorçages.

Principes (docs/architecture.md) :
- l'IA lit, le code calcule : aucune mesure ne vient de l'extraction ;
- aucune valeur en dur : densité et facteur K sont passés en paramètres par
  l'appelant, qui les lit dans la base via la couche d'accès
  (``data/acces.py`` : ``get_matiere``, ``get_parametre``) — voir
  :func:`construire_flan_depuis_base`.

Limites V1 :
- plis tous parallèles (c'est le périmètre du schéma ``ProfilPliage`` : les plis
  multi-directions ne sont pas représentables, prévus en V2) ;
- les positions des trous et chanfreins ne sont pas extraites du plan : le
  polygone du flan est le **rectangle englobant** ; les chanfreins et coins
  arrondis sont pris en compte analytiquement dans les surfaces et périmètres.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from generateur_devis.schema.piece import Aile, PieceExtraite, Pli, ProfilPliage, Trou
from generateur_devis.ui.formatage import formater_valeur

Point2D = tuple[float, float]


class ErreurGeometrie(ValueError):
    """La pièce ne peut pas être construite (données manquantes ou contradictoires)."""


class Flan(BaseModel):
    """La pièce à plat et ses mesures, calculées par le code."""

    model_config = ConfigDict(extra="forbid")

    longueur_developpee_mm: float
    """Longueur développée du profil de pliage, en mm."""
    largeur_mm: float
    """Largeur d'extrusion du profil (dimension le long des plis), en mm."""
    epaisseur_mm: float
    polygone_englobant: list[Point2D]
    """Rectangle englobant du flan (positions des trous/chanfreins non extraites en V1)."""
    surface_englobant_mm2: float
    surface_nette_mm2: float
    """Surface englobant moins trous et coins coupés (chanfreins, rayons)."""
    masse_flan_kg: float
    """Masse de matière achetée : rectangle englobant × e × densité (§2.2)."""
    masse_nette_kg: float
    """Masse de la pièce finie : surface nette × e × densité (contrôles §6)."""
    longueur_coupe_mm: float
    """Périmètre extérieur (corrigé des coins coupés) + périmètres des trous."""
    nombre_amorcages: int
    """1 contour extérieur + nombre de contours intérieurs (quantités incluses)."""


# ---------------------------------------------------------------------------
# Formule du développé (§2.4 logique_metier.md)
# ---------------------------------------------------------------------------


def calculer_ba(angle_degres: float, rayon_interieur: float, epaisseur: float, facteur_k: float) -> float:
    """BA (bend allowance) = π × angle/180 × (R + K × e), en mm."""
    return math.pi * angle_degres / 180 * (rayon_interieur + facteur_k * epaisseur)


def calculer_bd(angle_degres: float, rayon_interieur: float, epaisseur: float, facteur_k: float) -> float:
    """BD (bend deduction) = 2 × (R + e) × tan(angle/2) − BA, en mm."""
    return (
        2 * (rayon_interieur + epaisseur) * math.tan(math.radians(angle_degres) / 2)
        - calculer_ba(angle_degres, rayon_interieur, epaisseur, facteur_k)
    )


def rayon_pli(pli: Pli, rayon_general: float | None, indice: int) -> float:
    """Rayon intérieur d'un pli : cote du pli, sinon note générale, sinon erreur."""
    rayon = pli.rayon_interieur if pli.rayon_interieur is not None else rayon_general
    if rayon is None:
        msg = f"Rayon de pliage non coté (pli {indice}) et aucune note générale de rayon."
        raise ErreurGeometrie(msg)
    if rayon <= 0:
        msg = f"Rayon de pliage nul ou négatif (pli {indice}) : {rayon} mm."
        raise ErreurGeometrie(msg)
    return rayon


def verifier_alternance(profil: ProfilPliage) -> None:
    """Erreur si le profil est vide ou n'alterne pas aile/pli (début et fin = aile).

    Raises:
        ErreurGeometrie: "Profil de pliage incohérent : ailes et plis doivent alterner,
            en commençant et en finissant par une aile."
    """
    elements = profil.elements
    alterne = len(elements) % 2 == 1 and all(
        isinstance(e, Aile if i % 2 == 0 else Pli) for i, e in enumerate(elements)
    )
    if not alterne:
        msg = (
            "Profil de pliage incohérent : ailes et plis doivent alterner, "
            "en commençant et en finissant par une aile."
        )
        raise ErreurGeometrie(msg)


def longueur_developpee(piece: PieceExtraite, facteur_k: float) -> float:
    """Longueur développée du profil de pliage, en mm.

    - cotation intérieure : Σ ailes + Σ BA ;
    - cotation extérieure : Σ ailes − Σ BD ;
    - pièce plate (une seule aile) : longueur de l'aile.

    Raises:
        ErreurGeometrie: profil absent, vide ou non alterné, cotation inconnue,
            rayon non coté, ou développé nul/négatif (cotes contradictoires).
    """
    profil = piece.profil_pliage
    if profil is None:
        msg = "Profil de pliage absent : impossible de construire le flan."
        raise ErreurGeometrie(msg)
    verifier_alternance(profil)

    ailes = [e for e in profil.elements if isinstance(e, Aile)]
    plis = [e for e in profil.elements if isinstance(e, Pli)]
    if not plis:
        return ailes[0].longueur

    epaisseur = _epaisseur(piece)
    total_ailes = sum(a.longueur for a in ailes)
    rayons = [rayon_pli(p, profil.rayon_pliage_general, i) for i, p in enumerate(plis)]

    if profil.cotation == "interieure":
        developpe = total_ailes + sum(
            calculer_ba(p.angle, r, epaisseur, facteur_k) for p, r in zip(plis, rayons, strict=True)
        )
    elif profil.cotation == "exterieure":
        developpe = total_ailes - sum(
            calculer_bd(p.angle, r, epaisseur, facteur_k) for p, r in zip(plis, rayons, strict=True)
        )
    else:
        msg = "Cotation du profil inconnue : impossible de choisir entre BA et BD."
        raise ErreurGeometrie(msg)

    if developpe <= 0:
        msg = (
            f"Cotes contradictoires : longueur développée négative ou nulle "
            f"({formater_valeur('longueur_mm', developpe)} mm) "
            f"à partir des ailes cotées {profil.cotation}."
        )
        raise ErreurGeometrie(msg)
    return developpe


def _epaisseur(piece: PieceExtraite) -> float:
    """Épaisseur de la tôle, ou erreur si non lue sur le plan."""
    e = piece.matiere.epaisseur.valeur
    if e is None or e <= 0:
        msg = "Épaisseur de tôle absente ou invalide : impossible de construire le flan."
        raise ErreurGeometrie(msg)
    return e


# ---------------------------------------------------------------------------
# Aires et périmètres des éléments de contour
# ---------------------------------------------------------------------------


def aire_trou(trou: Trou) -> float:
    """Aire d'un trou selon sa forme, multipliée par ``quantite``, en mm².

    Oblong : ``longueur`` est la longueur hors tout (rectangle central + 2 demi-cercles).

    Raises:
        ErreurGeometrie: forme « autre » (aire indéterminable) ou dimensions manquantes.
    """
    if trou.forme == "rond":
        if trou.diametre is None:
            msg = "Trou rond sans diamètre."
            raise ErreurGeometrie(msg)
        aire_un = math.pi * (trou.diametre / 2) ** 2
    elif trou.forme in ("carre", "rectangulaire"):
        if trou.longueur is None or trou.largeur is None:
            msg = f"Trou {trou.forme} sans longueur/largeur."
            raise ErreurGeometrie(msg)
        aire_un = trou.longueur * trou.largeur
    elif trou.forme == "oblong":
        if trou.longueur is None or trou.largeur is None:
            msg = "Trou oblong sans longueur/largeur."
            raise ErreurGeometrie(msg)
        aire_un = (trou.longueur - trou.largeur) * trou.largeur + math.pi * (trou.largeur / 2) ** 2
    else:  # « autre » : signaler plutôt qu'inventer
        msg = "Aire indéterminable pour un trou de forme « autre »."
        raise ErreurGeometrie(msg)
    return aire_un * trou.quantite


def perimetre_trou(trou: Trou) -> float:
    """Périmètre d'un trou selon sa forme, multiplié par ``quantite``, en mm."""
    if trou.forme == "rond":
        if trou.diametre is None:
            msg = "Trou rond sans diamètre."
            raise ErreurGeometrie(msg)
        perimetre_un = math.pi * trou.diametre
    elif trou.forme in ("carre", "rectangulaire"):
        if trou.longueur is None or trou.largeur is None:
            msg = f"Trou {trou.forme} sans longueur/largeur."
            raise ErreurGeometrie(msg)
        perimetre_un = 2 * (trou.longueur + trou.largeur)
    elif trou.forme == "oblong":
        if trou.longueur is None or trou.largeur is None:
            msg = "Trou oblong sans longueur/largeur."
            raise ErreurGeometrie(msg)
        perimetre_un = 2 * (trou.longueur - trou.largeur) + math.pi * trou.largeur
    else:
        msg = "Périmètre indéterminable pour un trou de forme « autre »."
        raise ErreurGeometrie(msg)
    return perimetre_un * trou.quantite


def _corrections_coins(piece: PieceExtraite) -> tuple[float, float]:
    """Corrections de surface (mm²) et de périmètre (mm) des coins coupés.

    Chanfrein c1×c2 : retire un triangle (c1×c2/2) et remplace deux segments
    par l'hypoténuse. Rayon r : retire (1 − π/4) r² et remplace 2r par un quart
    de cercle. Positions non extraites en V1 : on suppose des coins à 90°.
    """
    surface = 0.0
    perimetre = 0.0
    for coin in piece.contours.coins:
        if coin.type == "chanfrein":
            if coin.cote1 is None:
                msg = "Chanfrein sans cote."
                raise ErreurGeometrie(msg)
            c1 = coin.cote1
            c2 = coin.cote2 if coin.cote2 is not None else c1
            surface -= coin.quantite * c1 * c2 / 2
            perimetre += coin.quantite * (math.hypot(c1, c2) - c1 - c2)
        else:  # rayon
            if coin.rayon is None:
                msg = "Coin arrondi sans rayon."
                raise ErreurGeometrie(msg)
            r = coin.rayon
            surface -= coin.quantite * (1 - math.pi / 4) * r**2
            perimetre += coin.quantite * (math.pi * r / 2 - 2 * r)
    return surface, perimetre


# ---------------------------------------------------------------------------
# Construction du flan
# ---------------------------------------------------------------------------


def construire_flan(
    piece: PieceExtraite,
    densite_kg_dm3: float,
    facteur_k: float,
) -> Flan:
    """Construire le flan (pièce à plat) et ses mesures.

    Args:
        piece: pièce extraite du plan (schéma ``piece.py``).
        densite_kg_dm3: densité de la matière, lue en base par l'appelant.
        facteur_k: facteur neutre K, lu en base par l'appelant.

    Raises:
        ErreurGeometrie: données manquantes ou contradictoires (voir les
            messages : profil, cotation, rayon, épaisseur, largeur, trous…).
    """
    if densite_kg_dm3 <= 0:
        msg = f"Densité invalide : {densite_kg_dm3} kg/dm³."
        raise ErreurGeometrie(msg)
    epaisseur = _epaisseur(piece)
    developpe = longueur_developpee(piece, facteur_k)

    largeur = piece.encombrement.largeur.valeur
    if largeur is None or largeur <= 0:
        msg = "Largeur d'encombrement absente ou invalide : impossible de construire le flan."
        raise ErreurGeometrie(msg)

    surface_englobant = developpe * largeur
    surface_trous = sum(aire_trou(t) for t in piece.contours.trous)
    perimetre_trous = sum(perimetre_trou(t) for t in piece.contours.trous)
    delta_surface_coins, delta_perimetre_coins = _corrections_coins(piece)

    surface_nette = surface_englobant - surface_trous + delta_surface_coins
    if surface_nette <= 0:
        msg = (
            f"Surface nette négative ou nulle "
            f"({formater_valeur('surface_mm2', surface_nette)} mm²) : "
            "les découpes dépassent la surface du flan (cotes contradictoires)."
        )
        raise ErreurGeometrie(msg)

    perimetre_exterieur = 2 * (developpe + largeur) + delta_perimetre_coins
    longueur_coupe = perimetre_exterieur + perimetre_trous
    nombre_amorcages = 1 + sum(t.quantite for t in piece.contours.trous)

    polygone: list[Point2D] = [(0.0, 0.0), (developpe, 0.0), (developpe, largeur), (0.0, largeur)]

    facteur_masse = epaisseur * densite_kg_dm3 * 1e-6  # mm² → kg (1 dm³ = 10⁶ mm³)
    return Flan(
        longueur_developpee_mm=developpe,
        largeur_mm=largeur,
        epaisseur_mm=epaisseur,
        polygone_englobant=polygone,
        surface_englobant_mm2=surface_englobant,
        surface_nette_mm2=surface_nette,
        masse_flan_kg=surface_englobant * facteur_masse,
        masse_nette_kg=surface_nette * facteur_masse,
        longueur_coupe_mm=longueur_coupe,
        nombre_amorcages=nombre_amorcages,
    )


def construire_flan_depuis_base(
    piece: PieceExtraite,
    matiere_id: str,
    session: object,
) -> Flan:
    """Construire le flan en lisant densité et facteur K dans les référentiels.

    Aucune valeur en dur : la densité vient de ``get_matiere`` et le facteur K
    du paramètre global ``facteur_k`` (``get_parametre``), via la couche d'accès.
    """
    from generateur_devis.data.acces import get_matiere, get_parametre

    matiere = get_matiere(matiere_id, session)  # type: ignore[arg-type]
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurGeometrie(msg)
    facteur_k = float(get_parametre("facteur_k", session))  # type: ignore[arg-type]
    return construire_flan(piece, matiere.densite_kg_dm3, facteur_k)


# ---------------------------------------------------------------------------
# Utilitaires bas niveau (conservés pour les contrôles de cohérence §6)
# ---------------------------------------------------------------------------


def aire_polygone_shoelace(points: list[Point2D]) -> float:
    """Aire d'un polygone par la formule de l'arpenteur, en mm²."""
    aire = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        aire += x1 * y2 - x2 * y1
    return abs(aire) / 2.0


def perimetre_polygone(points: list[Point2D]) -> float:
    """Périmètre d'un polygone fermé, en mm."""
    perimetre = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        perimetre += math.hypot(x2 - x1, y2 - y1)
    return perimetre


FormeTrou = Literal["rond", "oblong", "carre", "rectangulaire", "autre"]
