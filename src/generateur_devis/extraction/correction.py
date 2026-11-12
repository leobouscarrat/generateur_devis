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

import math
import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from generateur_devis.extraction.extracteur import extraire_json
from generateur_devis.extraction.prompt import (
    prompt_systeme_correction,
    prompt_utilisateur_correction,
)
from generateur_devis.llm import creer_modele
from generateur_devis.llm.base import ErreurModele
from generateur_devis.schema.piece import (
    Aile,
    CoinCoupe,
    Composant,
    ElementProfil,
    PieceExtraite,
    ProfilPliage,
    Soudure,
    Trou,
)
from generateur_devis.ui.formatage import formater_valeur

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
    if liste is None:  # section nullable absente (profil_pliage null, #84)
        msg = (
            f"Chemin inapplicable (section absente) : {chemin} — la section "
            f"{nom_liste.split('.')[0]} n'existe pas dans la fiche."
        )
        raise ErreurCorrection(msg)
    if not 0 <= index < len(liste):
        msg = f"Index hors de la liste {nom_liste} ({len(liste)} élément(s)) : {index}."
        raise ErreurCorrection(msg)
    return liste, index, modele

CHEMINS_AUTORISES: frozenset[str] = frozenset(
    {
        "matiere.designation.valeur",
        "matiere.epaisseur.valeur",
        "encombrement.largeur.valeur",
        "profil_pliage.rayon_pliage_general",
    }
)
"""Chemins modifiables par l'assistant (remplacement scalaire uniquement).

Le type attendu n'est pas tenu ici : il vient du schéma Pydantic
(``_valider_remplacement``, #84)."""

_NATURES: dict[type, str] = {str: "un texte", float: "un nombre", int: "un entier"}
"""Libellé du type attendu dans les messages d'erreur."""


def _valider_remplacement(
    piece: PieceExtraite, chemin: str, valeur: Any
) -> tuple[BaseModel, str, Any]:
    """Valide un remplacement scalaire contre le schéma (#84).

    Chemin whitelisté, section parente présente, valeur non nulle (pas de
    suppression en V1), puis validation **stricte** du champ par son modèle
    Pydantic (type et contraintes du schéma : ni dict, ni liste, ni booléen,
    ni texte pour un nombre) ; nombre non fini refusé.

    Returns:
        (objet parent dans ``piece``, nom du champ, valeur validée).

    Raises:
        ErreurCorrection: message lisible, sans rien modifier.
    """
    if chemin not in CHEMINS_AUTORISES:
        msg = f"Chemin non autorisé : {chemin!r}."
        raise ErreurCorrection(msg)
    *sections, champ = chemin.split(".")
    parent: Any = piece
    for segment in sections:
        parent = getattr(parent, segment, None)
        if parent is None:
            msg = f"Chemin inapplicable (section absente) : {chemin}."
            raise ErreurCorrection(msg)
    libelle = LIBELLES_CHEMINS[chemin][0]
    if valeur is None:
        msg = f"Valeur vide pour {libelle} : la suppression n'est pas prise en charge."
        raise ErreurCorrection(msg)
    modele = type(parent)
    natures = [
        _NATURES.get(t, t.__name__)
        for t in get_args(modele.model_fields[champ].annotation)
        if isinstance(t, type) and t is not type(None)
    ]
    attendu = f" (attendu : {' ou '.join(natures)})" if natures else ""
    msg = f"Valeur incompatible pour {libelle} : « {_resume_valeur(valeur)} »{attendu}."
    try:
        valide = modele.__pydantic_validator__.validate_assignment(
            parent.model_copy(), champ, valeur, strict=True
        )
    except ValidationError as e:
        raise ErreurCorrection(msg) from e
    resultat = getattr(valide, champ)
    if isinstance(resultat, float) and not math.isfinite(resultat):
        raise ErreurCorrection(msg)
    return parent, champ, resultat


# --- Libellés d'affichage avant/après (issue #67) -----------------------------
# Garde-fous dans tests/test_correction.py : toute extension de la whitelist ou
# du schéma d'un élément sans libellé fait échouer les tests.

LIBELLES_CHEMINS: dict[str, tuple[str, str]] = {
    # chemin whitelisté -> (libellé affiché, clé passée à formater_valeur)
    "matiere.designation.valeur": ("Matière", "designation"),
    "matiere.epaisseur.valeur": ("Épaisseur (mm)", "epaisseur_mm"),
    "encombrement.largeur.valeur": ("Largeur d'encombrement (mm)", "largeur_mm"),
    "profil_pliage.rayon_pliage_general": ("Rayon de pliage général (mm)", "rayon_mm"),
}
"""Mêmes libellés que les champs de l'écran de validation (ui/app.py)."""

LIBELLES_LISTES: dict[str, str] = {
    "composants": "Composant",
    "contours.trous": "Trou",
    "contours.coins": "Coin",
    "soudures": "Soudure",
    "profil_pliage.elements": "Profil",
}
"""Libellé d'un élément de chaque liste modifiable."""

LIBELLES_CHAMPS_ELEMENT: dict[str, tuple[str, str]] = {
    # champ d'un élément (Trou, CoinCoupe, Soudure, Composant, Aile, Pli)
    # -> (libellé affiché, clé passée à formater_valeur)
    "forme": ("Forme", "forme"),
    "diametre": ("Diamètre (mm)", "diametre_mm"),
    "longueur": ("Longueur (mm)", "longueur_mm"),
    "largeur": ("Largeur (mm)", "largeur_mm"),
    "quantite": ("Quantité", "quantite"),
    "angle": ("Angle (°)", "angle"),
    "sens": ("Sens", "sens"),
    "rayon_interieur": ("Rayon intérieur (mm)", "rayon_mm"),
    "rayon": ("Rayon (mm)", "rayon_mm"),
    "cote1": ("Cote 1 (mm)", "cote1_mm"),
    "cote2": ("Cote 2 (mm)", "cote2_mm"),
    "gorge": ("Gorge (mm)", "gorge_mm"),
    "designation": ("Désignation", "designation"),
    "type": ("Type", "type"),
    "filetage": ("Filetage", "filetage"),
    "norme": ("Norme", "norme"),
    "tolerance": ("Tolérance", "tolerance"),
    "tolerance_geometrique": ("Tolérance géométrique", "tolerance_geometrique"),
    "fraisurage": ("Fraisurage", "fraisurage"),
    "procede": ("Procédé", "procede"),
    "type_joint": ("Type de joint", "type_joint"),
    "texte": ("Annotation", "texte"),
}

CHAMPS_MASQUES: frozenset[str] = frozenset({"confiance", "source"})
"""Traces d'extraction, jamais affichées dans l'avant/après."""


def _formater(cle_format: str, valeur: Any) -> str:
    """``formater_valeur`` + littéraux à underscores lisibles
    (« ecrou_a_sertir » → « ecrou a sertir »)."""
    try:
        texte = formater_valeur(cle_format, valeur)
    except (OverflowError, ValueError):  # entier démesuré proposé par l'IA
        return "valeur hors limites"
    return texte.replace("_", " ") if isinstance(valeur, str) else texte


def _libelle_element(nom_liste: str, index: int, element: Any) -> str:
    """« Composant « CRIMPING NUTS… » », « Trou 2 », « Profil, élément 2 (pli) ».

    Position affichée = index + 1 ; un composant est désigné par sa désignation
    (repli sur la position si elle est vide).
    """
    libelle = LIBELLES_LISTES.get(nom_liste, nom_liste)
    if nom_liste == "profil_pliage.elements":
        return f"{libelle}, élément {index + 1} ({getattr(element, 'type', '?')})"
    designation = getattr(element, "designation", None)
    if nom_liste == "composants" and isinstance(designation, str) and designation.strip():
        return f"{libelle} « {designation.strip()} »"
    return f"{libelle} {index + 1}"


def _resume_element(element: BaseModel | dict[str, Any]) -> str:
    """« Forme : rond, Diamètre (mm) : 8.75, Quantité : 2 ».

    Champs non None, hors ``CHAMPS_MASQUES``, libellés de
    ``LIBELLES_CHAMPS_ELEMENT`` (repli : nom du champ).
    """
    champs = element.model_dump() if isinstance(element, BaseModel) else element
    morceaux = []
    for nom, valeur in champs.items():
        if nom in CHAMPS_MASQUES or valeur is None:
            continue
        libelle, cle = LIBELLES_CHAMPS_ELEMENT.get(nom, (str(nom), str(nom)))
        if isinstance(valeur, dict):
            texte = f"({_resume_element(valeur)})"
        elif isinstance(valeur, (list, tuple)):
            texte = f"{len(valeur)} élément(s)"
        else:
            texte = _formater(cle, valeur)
        morceaux.append(f"{libelle} : {texte}")
    return ", ".join(morceaux) or "—"


def _resume_profil(profil: ProfilPliage) -> str:
    """« Cotation exterieure, rayon général 2.00 mm : aile 42.00 / pli 90.00° haut »."""
    entete = f"Cotation {profil.cotation}"
    if profil.rayon_pliage_general is not None:
        entete += f", rayon général {_formater('rayon_mm', profil.rayon_pliage_general)} mm"
    elements = []
    for element in profil.elements:
        if isinstance(element, Aile):
            elements.append(f"aile {_formater('longueur_mm', element.longueur)}")
        else:
            texte = f"pli {_formater('angle', element.angle)}° {element.sens}"
            if element.rayon_interieur is not None:
                texte += f" R {_formater('rayon_mm', element.rayon_interieur)}"
            elements.append(texte)
    return f"{entete} : {' / '.join(elements)}"


def _ligne_repli(diff: DiffCorrection) -> tuple[str, str, str, str]:
    """Diff qui échouera à l'application : chemin brut, valeur sans traces.

    Le message d'erreur de ``appliquer`` (affiché par l'écran) fait foi.
    """
    return (diff.chemin or "", "—", _resume_valeur(diff.nouvelle_valeur), diff.justification)


def _resume_valeur(valeur: Any) -> str:
    """Valeur brute proposée par l'IA (dict, liste ou scalaire), sans repr Python."""
    if isinstance(valeur, dict):
        return _resume_element(valeur)
    if isinstance(valeur, (list, tuple)):
        return " ; ".join(_resume_valeur(v) for v in valeur) or "—"
    return _formater("", valeur)


def _lignes_diff(piece: PieceExtraite, diff: DiffCorrection) -> list[tuple[str, str, str, str]]:
    """Lignes lisibles d'un diff ; lève si le diff est inapplicable."""
    justification = diff.justification
    if diff.type == "remplacement":
        libelle, cle = LIBELLES_CHEMINS[diff.chemin or ""]
        _, _, nouvelle = _valider_remplacement(piece, diff.chemin or "", diff.nouvelle_valeur)
        avant = _lire_chemin(piece, diff.chemin or "")
        return [(libelle, _formater(cle, avant), _formater(cle, nouvelle), justification)]
    if diff.type == "creation_section":
        if diff.chemin != "profil_pliage" or piece.profil_pliage is not None:
            raise ErreurCorrection(diff.chemin or "")
        profil = ProfilPliage.model_validate(diff.nouvelle_valeur)
        return [("Profil de pliage", "— (absent)", _resume_profil(profil), justification)]
    if diff.type in ("ajout_element", "ajout_composant"):
        nom_liste = (diff.chemin or "") if diff.type == "ajout_element" else "composants"
        element = LISTES_ENRICHISSABLES[nom_liste].model_validate(diff.nouvelle_valeur)
        libelle = f"{LIBELLES_LISTES[nom_liste]} (ajout)"
        return [(libelle, "—", _resume_element(element), justification)]
    # modification_element : une ligne par champ qui change.
    liste, index, modele = _resoudre_element(piece, diff.chemin or "")
    actuel = liste[index]
    if not isinstance(diff.nouvelle_valeur, dict) or set(diff.nouvelle_valeur) - set(
        type(actuel).model_fields
    ):
        raise ErreurCorrection(diff.chemin or "")
    nouveau = TypeAdapter(modele).validate_python({**actuel.model_dump(), **diff.nouvelle_valeur})
    nom_liste = (diff.chemin or "").rsplit("[", 1)[0]
    prefixe = _libelle_element(nom_liste, index, actuel)
    lignes = []
    for champ in type(nouveau).model_fields:
        if champ in CHAMPS_MASQUES:
            continue
        valeur_avant = getattr(actuel, champ, None)
        valeur_apres = getattr(nouveau, champ)
        if valeur_avant == valeur_apres:
            continue
        libelle, cle = LIBELLES_CHAMPS_ELEMENT.get(champ, (champ, champ))
        lignes.append(
            (
                f"{prefixe} : {libelle}",
                _formater(cle, valeur_avant),
                _formater(cle, valeur_apres),
                justification,
            )
        )
    return lignes or [(f"{prefixe} : (aucun changement)", "—", "—", justification)]


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
            La pièce corrigée, validée par le schéma (l'originale n'est
            jamais modifiée).

        Raises:
            ErreurCorrection: chemin hors whitelist, type incompatible,
                ou pièce résultante invalide.
        """
        corrigee = piece.model_copy(deep=True)
        for diff in self.diffs:
            _appliquer_diff(corrigee, diff)
        try:
            return PieceExtraite.model_validate(corrigee.model_dump())
        except ValidationError as e:
            msg = f"La correction rend la fiche invalide : {e.errors()[0]['msg']}."
            raise ErreurCorrection(msg) from e

    def ligne_avant_apres(self, piece: PieceExtraite) -> list[tuple[str, str, str, str]]:
        """(champ, avant, après, justification) lisibles pour un deviseur.

        Libellés métier, nombres formatés par ``formater_valeur``, jamais de
        ``confiance``/``source`` ni de repr Pydantic. Un ``modification_element``
        produit une ligne par champ qui change. Ne lève jamais : un diff
        inapplicable donne une ligne de repli (le message de ``appliquer``,
        affiché par l'écran, fait foi).
        """
        lignes: list[tuple[str, str, str, str]] = []
        for diff in self.diffs:
            try:
                lignes.extend(_lignes_diff(piece, diff))
            except (
                ErreurCorrection,
                ValidationError,
                KeyError,
                TypeError,
                ValueError,
                OverflowError,
            ):
                lignes.append(_ligne_repli(diff))
        return lignes


def _lire_chemin(piece: PieceExtraite, chemin: str) -> Any:
    cible: Any = piece
    for segment in chemin.split("."):
        cible = getattr(cible, segment, None)
    return cible


def _appliquer_diff(piece: PieceExtraite, diff: DiffCorrection) -> None:
    if diff.type == "remplacement":
        parent, champ, valeur = _valider_remplacement(
            piece, diff.chemin or "", diff.nouvelle_valeur
        )
        setattr(parent, champ, valeur)
    elif diff.type == "creation_section":
        section = diff.chemin or ""
        modele_section = SECTIONS_CREABLES.get(section)
        if modele_section is None:
            msg = f"Section non créable : {section!r}."
            raise ErreurCorrection(msg)
        if getattr(piece, section, None) is not None:
            msg = f"La section {section} existe déjà dans la fiche — utilisez un remplacement."
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
    try:
        modele = creer_modele(nom_modele)
    except ValueError as e:  # désignation de modèle mal formée ou inconnue
        msg = f"Assistant indisponible : {e}"
        raise ErreurCorrection(msg) from e
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
    # Validation à la proposition = les règles d'``appliquer`` (source unique,
    # #84) : un diff inapplicable sur la fiche courante est rejeté avant
    # l'affichage avant/après. L'écran revalide à l'acceptation.
    try:
        proposition.appliquer(piece)
    except ErreurCorrection as e:
        msg = f"L'assistant propose une correction inapplicable : {e}"
        raise ErreurCorrection(msg) from e
    return proposition
