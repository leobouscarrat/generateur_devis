"""Assistant de correction en texte libre (issue #25, architecture §9).

Deuxième point d'appel IA du parcours : l'utilisateur décrit une correction
en texte libre (« c'est de l'inox 2 mm avec 4 écrous »), l'IA propose un
**diff** borné — jamais une pièce réécrite. Le diff est validé contre le
schéma, affiché avant/après, et l'utilisateur accepte ou refuse
explicitement : aucun changement sans accord.

Bornes V1 (tranchées dans la spec) :
- ``remplacement`` sur des chemins **whitelistés** uniquement ;
- ``ajout_composant`` pour la nomenclature (ex. les écrous du §4) ;
- ``suppression`` refusée (erreur explicite) ;
- application **transactionnelle** : un élément invalide annule tout le diff.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from generateur_devis.extraction.extracteur import extraire_json
from generateur_devis.extraction.prompt import (
    prompt_systeme_correction,
    prompt_utilisateur_correction,
)
from generateur_devis.llm import creer_modele
from generateur_devis.llm.base import ErreurModele
from generateur_devis.schema.piece import (
    CoinCoupe,
    Composant,
    ElementProfil,
    PieceExtraite,
    ProfilPliage,
    Soudure,
    Trou,
)

SECTIONS_CREABLES: dict[str, type] = {"profil_pliage": ProfilPliage}
"""Sections absentes que l'assistant peut créer d'un bloc (objet complet)."""

LISTES_ENRICHISSABLES: dict[str, type] = {
    "composants": Composant,
    "contours.trous": Trou,
    "contours.coins": CoinCoupe,
    "soudures": Soudure,
}
"""Listes auxquelles l'assistant peut ajouter un élément (``ajout_element``)."""

ELEMENTS_MODIFIABLES: dict[str, Any] = {
    **LISTES_ENRICHISSABLES,
    "profil_pliage.elements": ElementProfil,
}
"""Listes dont un élément existant peut être corrigé (``modification_element``,
chemin ``liste[index]``). Les éléments du profil de pliage sont validés par
l'union discriminée ``ElementProfil`` (aile ou pli)."""

_MOTIF_ELEMENT = re.compile(r"^(?P<liste>[\w.]+)\[(?P<index>\d+)\]$")


def _resoudre_element(
    piece: PieceExtraite, chemin: str
) -> tuple[list[Any], int, Any]:
    """Résout un chemin ``liste[index]`` vers (liste, index, modèle d'élément).

    Raises:
        ErreurCorrection: format invalide, liste non modifiable, index hors
            de la liste.
    """
    correspondance = _MOTIF_ELEMENT.match(chemin)
    if not correspondance:
        msg = f"Chemin d'élément invalide (attendu « liste[index] ») : {chemin!r}."
        raise ErreurCorrection(msg)
    nom_liste = correspondance.group("liste")
    modele = ELEMENTS_MODIFIABLES.get(nom_liste)
    if modele is None:
        msg = f"Liste non modifiable : {nom_liste!r}."
        raise ErreurCorrection(msg)
    index = int(correspondance.group("index"))
    liste = _lire_chemin(piece, nom_liste)
    if not 0 <= index < len(liste):
        msg = f"Index hors de la liste {nom_liste} ({len(liste)} élément(s)) : {index}."
        raise ErreurCorrection(msg)
    return liste, index, modele

CHEMINS_AUTORISES: dict[str, type] = {
    "matiere.designation.valeur": str,
    "matiere.epaisseur.valeur": float,
    "encombrement.largeur.valeur": float,
    "profil_pliage.rayon_pliage_general": float,
}
"""Chemins modifiables par l'assistant (remplacement scalaire uniquement)."""

class ErreurCorrection(Exception):
    """Proposition ou application de correction invalide (message lisible)."""


class DiffCorrection(BaseModel):
    """Une modification proposée par l'IA, avec sa justification."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "remplacement",
        "ajout_composant",
        "creation_section",
        "ajout_element",
        "modification_element",
    ]
    chemin: str | None = None
    nouvelle_valeur: Any
    justification: str = ""


class PropositionCorrection(BaseModel):
    """Réponse de l'assistant : le diff proposé + remarque éventuelle."""

    model_config = ConfigDict(extra="forbid")

    diffs: list[DiffCorrection] = Field(default_factory=list)
    remarque: str | None = None

    def appliquer(self, piece: PieceExtraite) -> PieceExtraite:
        """Applique le diff sur une copie de la pièce (transactionnel).

        Tous les chemins sont validés **avant** application ; la copie
        modifiée est re-validée par Pydantic — un seul élément invalide
        annule tout le diff (ErreurCorrection).

        Returns:
            La pièce corrigée (l'originale n'est jamais modifiée).

        Raises:
            ErreurCorrection: chemin hors whitelist, type incompatible,
                ou pièce résultante invalide.
        """
        corrigee = piece.model_copy(deep=True)
        for diff in self.diffs:
            _appliquer_diff(corrigee, diff)
        try:
            PieceExtraite.model_validate(corrigee.model_dump())
        except ValidationError as e:
            msg = f"La correction rend la fiche invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e
        return corrigee

    def ligne_avant_apres(self, piece: PieceExtraite) -> list[tuple[str, str, str, str]]:
        """Lignes d'affichage (champ, avant, après, justification)."""
        lignes = []
        for diff in self.diffs:
            if diff.type == "remplacement":
                avant = _lire_chemin(piece, diff.chemin or "")
                lignes.append(
                    (diff.chemin or "", str(avant), str(diff.nouvelle_valeur), diff.justification)
                )
            elif diff.type == "creation_section":
                lignes.append(
                    (diff.chemin or "", "— (absente)", str(diff.nouvelle_valeur), diff.justification)
                )
            elif diff.type == "modification_element":
                try:
                    liste, index, _ = _resoudre_element(piece, diff.chemin or "")
                    avant = str(liste[index])
                except ErreurCorrection:
                    avant = "—"
                lignes.append((diff.chemin or "", avant, str(diff.nouvelle_valeur), diff.justification))
            else:
                etiquettes = diff.chemin or "composants"
                lignes.append((etiquettes, "—", str(diff.nouvelle_valeur), diff.justification))
        return lignes


def _lire_chemin(piece: PieceExtraite, chemin: str) -> Any:
    cible: Any = piece
    for segment in chemin.split("."):
        cible = getattr(cible, segment, None)
    return cible


def _appliquer_diff(piece: PieceExtraite, diff: DiffCorrection) -> None:
    if diff.type == "remplacement":
        chemin = diff.chemin or ""
        if chemin not in CHEMINS_AUTORISES:
            msg = f"Chemin non autorisé : {chemin!r}."
            raise ErreurCorrection(msg)
        type_attendu = CHEMINS_AUTORISES[chemin]
        try:
            valeur = type_attendu(diff.nouvelle_valeur)
        except (TypeError, ValueError) as e:
            msg = f"Valeur incompatible pour {chemin} : {diff.nouvelle_valeur!r}."
            raise ErreurCorrection(msg) from e
        segments = chemin.split(".")
        cible: Any = piece
        for segment in segments[:-1]:
            cible = getattr(cible, segment, None)
            if cible is None:
                msg = f"Chemin inapplicable (section absente) : {chemin}."
                raise ErreurCorrection(msg)
        setattr(cible, segments[-1], valeur)
    elif diff.type == "creation_section":
        section = diff.chemin or ""
        modele_section = SECTIONS_CREABLES.get(section)
        if modele_section is None:
            msg = f"Section non créable : {section!r}."
            raise ErreurCorrection(msg)
        if getattr(piece, section, None) is not None:
            msg = f"Section déjà présente : {section} — utilisez un remplacement."
            raise ErreurCorrection(msg)
        try:
            setattr(piece, section, modele_section.model_validate(diff.nouvelle_valeur))
        except ValidationError as e:
            msg = f"Section invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e
    elif diff.type == "ajout_element":
        chemin_liste = diff.chemin or ""
        modele_element = LISTES_ENRICHISSABLES.get(chemin_liste)
        if modele_element is None:
            msg = f"Liste non enrichissable : {chemin_liste!r}."
            raise ErreurCorrection(msg)
        try:
            element = modele_element.model_validate(diff.nouvelle_valeur)
        except ValidationError as e:
            msg = f"Élément invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e
        liste = _lire_chemin(piece, chemin_liste)
        liste.append(element)
    elif diff.type == "modification_element":
        liste, index, modele = _resoudre_element(piece, diff.chemin or "")
        if not isinstance(diff.nouvelle_valeur, dict):
            msg = "Une modification d'élément attend un objet de champs à fusionner."
            raise ErreurCorrection(msg)
        actuel = liste[index]
        champs_inconnus = set(diff.nouvelle_valeur) - set(type(actuel).model_fields)
        if champs_inconnus:
            msg = f"Champ(s) inconnu(s) de {type(actuel).__name__} : {sorted(champs_inconnus)}."
            raise ErreurCorrection(msg)
        try:
            liste[index] = TypeAdapter(modele).validate_python(
                {**actuel.model_dump(), **diff.nouvelle_valeur}
            )
        except ValidationError as e:
            msg = f"Élément corrigé invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e
    else:  # ajout_composant (conservé pour compatibilité ; ajout_element le généralise)
        try:
            composant = Composant.model_validate(diff.nouvelle_valeur)
        except ValidationError as e:
            msg = f"Composant invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e
        piece.composants.append(composant)


def proposer_correction(piece: PieceExtraite, texte: str, nom_modele: str) -> PropositionCorrection:
    """Demande à l'IA un diff de correction pour la pièce courante.

    Args:
        piece: fiche courante (état du formulaire de validation).
        texte: correction en texte libre de l'utilisateur.
        nom_modele: désignation du modèle (``llm.creer_modele``) — aucune
            valeur en dur.

    Returns:
        La proposition validée (chemins whitelistés, JSON conforme).

    Raises:
        ErreurCorrection: réponse IA illisible ou non conforme.
    """
    if not texte.strip():
        msg = "Décrivez la correction à apporter."
        raise ErreurCorrection(msg)
    modele = creer_modele(nom_modele)
    try:
        reponse = modele.generer(
            prompt_systeme_correction(),
            prompt_utilisateur_correction(piece.model_dump_json(), texte),
            [],
        )
    except ErreurModele as e:
        msg = f"Assistant indisponible : {e}"
        raise ErreurCorrection(msg) from e
    try:
        proposition = PropositionCorrection.model_validate_json(extraire_json(reponse.texte))
    except (ValidationError, ValueError) as e:
        msg = "Réponse de l'assistant illisible — reformulez la correction."
        raise ErreurCorrection(msg) from e
    # Validation précoce des chemins : une proposition hors whitelist ou
    # inapplicable (section absente de la fiche courante) est rejetée
    # immédiatement, avant même l'affichage avant/après.
    for diff in proposition.diffs:
        if diff.type == "modification_element":
            try:
                _resoudre_element(piece, diff.chemin or "")
            except ErreurCorrection as e:
                msg = f"L'assistant propose une modification d'élément impossible : {e}"
                raise ErreurCorrection(msg) from e
            continue
        if diff.type == "ajout_element":
            if (diff.chemin or "") not in LISTES_ENRICHISSABLES:
                msg = f"L'assistant propose une liste non enrichissable : {diff.chemin!r}."
                raise ErreurCorrection(msg)
            continue
        if diff.type == "creation_section":
            section = diff.chemin or ""
            if section not in SECTIONS_CREABLES:
                msg = f"L'assistant propose une section non créable : {section!r}."
                raise ErreurCorrection(msg)
            if getattr(piece, section, None) is not None:
                msg = (
                    f"L'assistant propose de créer {section!r} alors que la section "
                    "existe déjà dans la fiche courante."
                )
                raise ErreurCorrection(msg)
            continue
        if diff.type != "remplacement":
            continue
        if diff.chemin not in CHEMINS_AUTORISES:
            msg = f"L'assistant propose un chemin non autorisé : {diff.chemin!r}."
            raise ErreurCorrection(msg)
        cible: Any = piece
        for segment in (diff.chemin or "").split(".")[:-1]:
            cible = getattr(cible, segment, None)
            if cible is None:
                msg = (
                    f"L'assistant propose un chemin inapplicable : {diff.chemin!r} "
                    "(section absente de la fiche courante)."
                )
                raise ErreurCorrection(msg)
    return proposition
