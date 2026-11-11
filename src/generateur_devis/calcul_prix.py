"""Moteur de calcul des coûts — blocs 1 à 3 (matière, découpe, pliage).

Chiffrage déterministe d'une pièce de tôlerie, à partir de sa géométrie
(``geometrie.construire_flan``, issue #7) et des référentiels en base lus via
``data/acces.py`` : **aucune valeur en dur** (prix matière, rendement de
calepinage, vitesses de coupe, temps de pliage, taux horaires et réglages
viennent tous des tables).

Formules : docs/logique_metier.md §3 (blocs 1–3). Chaque bloc sépare :

- le **coût variable unitaire** (payé à la pièce) ;
- le **coût fixe de lot** (réglages, payé une fois par lot) — prérequis des
  paliers de quantité (§5), agrégés en 3.3 (#15).

Limites V1 assumées :

- le temps de retournement de la presse plieuse (``temps_retournement_s`` de
  la table ``temps_pliage``) n'est **pas** compté : la référence piece_003
  (§8.3 : 2 plis × 8 s = 16 s) l'exclut ;
- le calepinage est approximé par un rendement fixe (§10).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.data.acces import (
    get_matiere,
    get_parametre,
    get_poste,
    get_temps_pliage,
    get_vitesse_coupe,
)
from generateur_devis.geometrie import Flan
from generateur_devis.schema.piece import PieceExtraite


class ErreurChiffrage(Exception):
    """Donnée de référence manquante ou invalide pour le chiffrage."""


class BlocMatiere(BaseModel):
    """Bloc 1 — matière (tôle consommée, chutes incluses)."""

    model_config = ConfigDict(extra="forbid")

    masse_flan_kg: float
    rendement_calepinage: float
    prix_matiere_eur_kg: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float = 0.0


class BlocDecoupe(BaseModel):
    """Bloc 2 — découpe laser (contour extérieur + contours intérieurs)."""

    model_config = ConfigDict(extra="forbid")

    longueur_coupe_mm: float
    nombre_amorcages: int
    vitesse_m_min: float
    temps_amorcage_s: float
    temps_cycle_s: float
    taux_horaire_eur_h: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocPliage(BaseModel):
    """Bloc 3 — pliage (nb plis × temps par pli, sans retournement en V1)."""

    model_config = ConfigDict(extra="forbid")

    nb_plis: int
    temps_par_pli_s: float
    temps_cycle_s: float
    taux_horaire_eur_h: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocsCout(BaseModel):
    """Les trois premiers blocs de coût d'une pièce."""

    model_config = ConfigDict(extra="forbid")

    matiere: BlocMatiere
    decoupe: BlocDecoupe
    pliage: BlocPliage


def calculer_bloc_matiere(flan: Flan, matiere_id: str, session: Session) -> BlocMatiere:
    """Bloc 1 : coût = masse flan ÷ rendement calepinage × prix matière.

    La masse du flan (rectangle englobant, trous et chanfreins en chute)
    est celle calculée par ``geometrie.construire_flan`` (§2.2).

    Raises:
        ErreurChiffrage: matière inconnue du référentiel ou rendement
            de calepinage nul.
    """
    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurChiffrage(msg)
    rendement = float(get_parametre("rendement_calepinage", session))
    if rendement <= 0:
        msg = f"Rendement de calepinage invalide : {rendement}."
        raise ErreurChiffrage(msg)
    cout = flan.masse_flan_kg / rendement * matiere.prix_eur_kg
    return BlocMatiere(
        masse_flan_kg=flan.masse_flan_kg,
        rendement_calepinage=rendement,
        prix_matiere_eur_kg=matiere.prix_eur_kg,
        cout_variable_eur=cout,
    )


def calculer_bloc_decoupe(flan: Flan, famille_matiere: str, session: Session) -> BlocDecoupe:
    """Bloc 2 : temps = longueur ÷ vitesse + amorçages ; coût × taux laser.

    La vitesse de coupe vient de la table ``vitesses_coupe`` (poste × famille
    × épaisseur) ; le réglage/programmation du poste est un coût fixe de lot.

    Raises:
        ErreurChiffrage: poste de découpe inconnu, ou pas de vitesse de
            coupe pour la famille × épaisseur.
    """
    poste_id = str(get_parametre("poste_decoupe", session))
    poste = get_poste(poste_id, session)
    if poste is None:
        msg = f"Poste de découpe inconnu dans le référentiel : {poste_id!r}."
        raise ErreurChiffrage(msg)
    vitesse = get_vitesse_coupe(poste_id, famille_matiere, flan.epaisseur_mm, session)
    if vitesse is None:
        msg = (
            f"Pas de vitesse de coupe pour {poste_id!r}, famille "
            f"{famille_matiere!r}, épaisseur {flan.epaisseur_mm} mm."
        )
        raise ErreurChiffrage(msg)
    temps_s = (
        flan.longueur_coupe_mm / 1000.0 / vitesse.vitesse_m_min * 60.0
        + flan.nombre_amorcages * vitesse.temps_amorcage_s
    )
    taux = poste.taux_horaire_eur_h
    return BlocDecoupe(
        longueur_coupe_mm=flan.longueur_coupe_mm,
        nombre_amorcages=flan.nombre_amorcages,
        vitesse_m_min=vitesse.vitesse_m_min,
        temps_amorcage_s=vitesse.temps_amorcage_s,
        temps_cycle_s=temps_s,
        taux_horaire_eur_h=taux,
        cout_variable_eur=temps_s / 3600.0 * taux,
        cout_fixe_eur_par_lot=poste.temps_reglage_min / 60.0 * taux,
    )


def calculer_bloc_pliage(piece: PieceExtraite, flan: Flan, session: Session) -> BlocPliage:
    """Bloc 3 : temps = nb plis × temps par pli (tranche ``temps_pliage``).

    La tranche est choisie par la dimension de la pièce (longueur de pli =
    largeur d'extrusion du flan) et l'épaisseur. Le réglage de la plieuse
    est un coût fixe de lot. Une pièce sans pli donne un bloc à zéro.

    Raises:
        ErreurChiffrage: poste de pliage inconnu, ou aucune tranche de
            temps de pliage ne couvrant la pièce (si elle a des plis).
    """
    nb_plis = piece.profil_pliage.nb_plis if piece.profil_pliage else 0
    poste_id = str(get_parametre("poste_pliage", session))
    poste = get_poste(poste_id, session)
    if poste is None:
        msg = f"Poste de pliage inconnu dans le référentiel : {poste_id!r}."
        raise ErreurChiffrage(msg)
    taux = poste.taux_horaire_eur_h
    if nb_plis == 0:
        return BlocPliage(
            nb_plis=0,
            temps_par_pli_s=0.0,
            temps_cycle_s=0.0,
            taux_horaire_eur_h=taux,
            cout_variable_eur=0.0,
            cout_fixe_eur_par_lot=0.0,
        )
    tranche = get_temps_pliage(flan.largeur_mm, flan.epaisseur_mm, session)
    if tranche is None:
        msg = (
            f"Aucune tranche de temps de pliage ne couvre {flan.largeur_mm} mm "
            f"× {flan.epaisseur_mm} mm."
        )
        raise ErreurChiffrage(msg)
    temps_s = nb_plis * tranche.temps_par_pli_s
    return BlocPliage(
        nb_plis=nb_plis,
        temps_par_pli_s=tranche.temps_par_pli_s,
        temps_cycle_s=temps_s,
        taux_horaire_eur_h=taux,
        cout_variable_eur=temps_s / 3600.0 * taux,
        cout_fixe_eur_par_lot=poste.temps_reglage_min / 60.0 * taux,
    )


def calculer_blocs_1_3(
    piece: PieceExtraite, flan: Flan, matiere_id: str, session: Session
) -> BlocsCout:
    """Calcule les blocs 1 à 3 du chiffrage (matière, découpe, pliage).

    Args:
        piece: pièce extraite du plan (schéma ``piece.py``).
        flan: flan construit par ``geometrie.construire_flan`` — ses mesures
            (masse, longueur de coupe, amorçages) sont consommées telles
            quelles, jamais recalculées.
        matiere_id: matière retenue pour le chiffrage (référentiel).
        session: session SQLAlchemy sur la base de référence.

    Returns:
        Les trois blocs, chacun avec ses grandeurs intermédiaires et la
        séparation coût variable unitaire / coût fixe de lot.
    """
    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurChiffrage(msg)
    return BlocsCout(
        matiere=calculer_bloc_matiere(flan, matiere_id, session),
        decoupe=calculer_bloc_decoupe(flan, matiere.famille, session),
        pliage=calculer_bloc_pliage(piece, flan, session),
    )
