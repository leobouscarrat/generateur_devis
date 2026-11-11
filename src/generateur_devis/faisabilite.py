"""Moteur de règles de faisabilité (issue #9).

Évalue la faisabilité d'une pièce à partir de la pièce extraite, du flan
(``geometrie.construire_flan``) et des référentiels en base. Chaque règle
produit un **constat** : une **alerte** (à vérifier) ou un **blocage** (devis
impossible en l'état) — docs/architecture.md §3b.

Aucune valeur en dur : les seuils (multiples de l'épaisseur) sont des
paramètres globaux lus en base (``regle_diam_trou_min_e``, ``regle_aile_min_e``,
``regle_rayon_min_e``), les épaisseurs et formats de tôle viennent de
``epaisseurs_dispo``, les compatibilités de ``traitements``.

Limites V1 (données absentes, voir spécification de l'issue) :
- distances trou/bord et trou/pli : positions des trous non extraites ;
- longueur de plieuse : pas de dimension machine dans ``postes`` ;
- épaisseur min pour écrou à sertir : pas de colonne dans ``composants``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.data.acces import (
    TRAITEMENT_ID_PAR_TYPE,
    get_matiere,
    get_parametre,
    get_traitement,
    list_epaisseurs,
)
from generateur_devis.geometrie import ErreurGeometrie, construire_flan
from generateur_devis.schema.piece import Aile, PieceExtraite, Pli, TypeTraitement


class Constat(BaseModel):
    """Résultat d'une règle de faisabilité déclenchée."""

    model_config = ConfigDict(extra="forbid")

    regle: str
    """Identifiant stable de la règle, ex. ``diam_trou_min``."""
    severite: Literal["alerte", "blocage"]
    message: str
    """Message lisible, avec les valeurs ayant déclenché le constat."""
    champ: str | None = None
    """Champ concerné, ex. ``contours.trous[0]``."""


def _parse_format(format_mm: str) -> tuple[float, float]:
    """« 3000 × 1500 » → (3000.0, 1500.0)."""
    a, b = format_mm.lower().replace("x", "×").split("×")
    return float(a.strip()), float(b.strip())


def evaluer_faisabilite(
    piece: PieceExtraite,
    matiere_id: str,
    session: Session,
) -> list[Constat]:
    """Évalue toutes les règles applicables à la pièce.

    Une règle non applicable (ex. pas de trous, pas de traitement) est
    simplement absente du résultat. Une pièce conforme donne une liste vide.

    Args:
        piece: pièce extraite du plan.
        matiere_id: matière retenue pour le chiffrage (référentiel).
        session: session SQLAlchemy sur la base de référence.

    Returns:
        Les constats (alertes et blocages), dans l'ordre d'évaluation.

    Raises:
        ErreurGeometrie: matière inconnue du référentiel, ou flan non
            constructible (propagée de ``geometrie.construire_flan``).
    """
    constats: list[Constat] = []

    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurGeometrie(msg)
    facteur_k = float(get_parametre("facteur_k", session))
    flan = construire_flan(piece, matiere.densite_kg_dm3, facteur_k)
    e = flan.epaisseur_mm

    # --- Règle : épaisseur disponible + format de tôle (blocages) ----------
    dispos = list_epaisseurs(matiere_id, session)
    au_bon_format = [d for d in dispos if d.epaisseur_mm == e]
    if not au_bon_format:
        dispos_txt = ", ".join(str(d.epaisseur_mm) for d in dispos) or "aucune"
        constats.append(
            Constat(
                regle="epaisseur_dispo",
                severite="blocage",
                message=(
                    f"Épaisseur {e} mm non disponible pour {matiere_id} "
                    f"(disponibles : {dispos_txt} mm)."
                ),
                champ="matiere.epaisseur",
            )
        )
    else:
        tient = False
        for dispo in au_bon_format:
            if dispo.format_mm is None:
                continue
            a, b = _parse_format(dispo.format_mm)
            dims_tole = sorted((a, b))
            dims_flan = sorted((flan.longueur_developpee_mm, flan.largeur_mm))
            if dims_flan[0] <= dims_tole[0] and dims_flan[1] <= dims_tole[1]:
                tient = True
                break
        if not tient:
            constats.append(
                Constat(
                    regle="flan_dans_format",
                    severite="blocage",
                    message=(
                        f"Flan {flan.longueur_developpee_mm:.0f} × {flan.largeur_mm:.0f} mm "
                        f"hors format de tôle ({au_bon_format[0].format_mm} mm)."
                    ),
                    champ=None,
                )
            )
        if not any(d.en_stock for d in au_bon_format):
            constats.append(
                Constat(
                    regle="epaisseur_en_stock",
                    severite="alerte",
                    message=f"Épaisseur {e} mm disponible mais pas en stock (délai d'appro).",
                    champ="matiere.epaisseur",
                )
            )

    # --- Règle : diamètre de trou ≥ k × e (alerte) ---------------------------
    k_trou = float(get_parametre("regle_diam_trou_min_e", session))
    for i, trou in enumerate(piece.contours.trous):
        if trou.forme == "rond" and trou.diametre is not None and trou.diametre < k_trou * e:
            constats.append(
                Constat(
                    regle="diam_trou_min",
                    severite="alerte",
                    message=(
                        f"Trou Ø{trou.diametre} mm < {k_trou:g} × épaisseur "
                        f"({k_trou * e:g} mm) : perçage difficile, à vérifier."
                    ),
                    champ=f"contours.trous[{i}]",
                )
            )

    # --- Règles de pliage (alertes) ------------------------------------------
    if piece.profil_pliage is not None:
        profil = piece.profil_pliage
        k_aile = float(get_parametre("regle_aile_min_e", session))
        for i, element in enumerate(profil.elements):
            if isinstance(element, Aile) and element.longueur < k_aile * e:
                constats.append(
                    Constat(
                        regle="aile_min",
                        severite="alerte",
                        message=(
                            f"Aile {element.longueur} mm < {k_aile:g} × épaisseur "
                            f"({k_aile * e:g} mm) : minimum de l'outillage, à vérifier."
                        ),
                        champ=f"profil_pliage.elements[{i}]",
                    )
                )
        k_rayon = float(get_parametre("regle_rayon_min_e", session))
        for i, element in enumerate(profil.elements):
            if isinstance(element, Pli):
                rayon = (
                    element.rayon_interieur
                    if element.rayon_interieur is not None
                    else profil.rayon_pliage_general
                )
                if rayon is not None and rayon < k_rayon * e:
                    constats.append(
                        Constat(
                            regle="rayon_min",
                            severite="alerte",
                            message=(
                                f"Rayon {rayon} mm < {k_rayon:g} × épaisseur "
                                f"({k_rayon * e:g} mm) : risque de fissuration, à vérifier."
                            ),
                            champ=f"profil_pliage.elements[{i}]",
                        )
                    )

    # --- Règle : traitement compatible avec la matière (alerte) ---------------
    type_traitement: TypeTraitement | None = piece.traitement.type.valeur
    if type_traitement not in (None, "aucun"):
        traitement_id = TRAITEMENT_ID_PAR_TYPE.get(str(type_traitement))
        traitement = get_traitement(traitement_id, session) if traitement_id else None
        if traitement is not None and traitement.matieres_compatibles not in (None, "toutes"):
            compatibles = {f.strip() for f in traitement.matieres_compatibles.split(",")}
            if matiere.famille not in compatibles:
                constats.append(
                    Constat(
                        regle="traitement_compatible",
                        severite="alerte",
                        message=(
                            f"Traitement « {traitement.nom} » incompatible avec "
                            f"{matiere.famille} (compatibles : {traitement.matieres_compatibles})."
                        ),
                        champ="traitement.type",
                    )
                )

    return constats
