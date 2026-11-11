"""Agent conversationnel d'administration des référentiels (issue #34, §12).

L'administrateur décrit une mise à jour en texte libre (« le S235JR passe à
1,25 €/kg ») ; l'IA propose un **diff borné et validé**, jamais une écriture
directe : whitelist explicite des tables/champs, validation métier, affichage
avant/après, acceptation explicite, puis écriture + audit (5.1).

Bornes V1 : ``mise_a_jour`` sur la whitelist complète, ``creation`` limitée à
``traitements`` et ``composants`` ; suppression refusée ; la clé primaire
n'est jamais modifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from generateur_devis.data.audit import enregistrer_modification
from generateur_devis.data.tables import (
    BorneControle,
    Client,
    Composant,
    EpaisseurDispo,
    Matiere,
    Operation,
    Parametre,
    Poste,
    TempsPliage,
    Traitement,
    VitesseCoupe,
)
from generateur_devis.extraction.extracteur import extraire_json
from generateur_devis.extraction.prompt import (
    prompt_systeme_admin,
    prompt_utilisateur_admin,
)
from generateur_devis.llm import creer_modele
from generateur_devis.llm.base import ErreurModele
from generateur_devis.ui.formatage import formater_valeur


class ErreurAdmin(ValueError):
    """Proposition ou application invalide (message lisible pour l'écran)."""


@dataclass(frozen=True)
class Referentiel:
    """Description d'une table administrable (whitelist)."""

    modele: type
    pk: tuple[str, ...]  # colonnes de clé primaire (jamais modifiables)
    champs: dict[str, type]  # champs modifiables et leur type
    creation: bool = False
    champs_positifs: frozenset[str] = field(default=frozenset())
    """Champs numériques qui doivent rester strictement positifs (prix, taux, temps)."""
    cles_etrangeres: dict[str, str] = field(default_factory=dict)
    """Champ → table référencée (la valeur doit être une clé existante)."""


REFERENTIELS_MODIFIABLES: dict[str, Referentiel] = {
    "matieres": Referentiel(
        Matiere,
        ("id",),
        {
            "famille": str, "nuance": str, "norme": str,
            "densite_kg_dm3": float, "prix_eur_kg": float, "fournisseur": str,
        },
        champs_positifs=frozenset({"densite_kg_dm3", "prix_eur_kg"}),
    ),
    "epaisseurs_dispo": Referentiel(
        EpaisseurDispo,
        ("matiere_id", "epaisseur_mm"),
        {"format_mm": str, "surcout_pct": float, "en_stock": bool},
    ),
    "postes": Referentiel(
        Poste,
        ("id",),
        {"nom": str, "type": str, "taux_horaire_eur_h": float, "temps_reglage_min": float},
        champs_positifs=frozenset({"taux_horaire_eur_h", "temps_reglage_min"}),
    ),
    "vitesses_coupe": Referentiel(
        VitesseCoupe,
        ("poste_id", "famille", "epaisseur_mm"),
        {"vitesse_m_min": float, "temps_amorcage_s": float, "gaz": str},
        champs_positifs=frozenset({"vitesse_m_min", "temps_amorcage_s"}),
    ),
    "temps_pliage": Referentiel(
        TempsPliage,
        ("categorie", "dim_max_mm", "epaisseur_max_mm"),
        {"temps_par_pli_s": float, "temps_retournement_s": float, "nb_operateurs": int},
        champs_positifs=frozenset({"temps_par_pli_s"}),
    ),
    "operations": Referentiel(
        Operation,
        ("id",),
        {"nom": str, "poste_id": str, "temps_s": float, "unite": str},
        champs_positifs=frozenset({"temps_s"}),
        cles_etrangeres={"poste_id": "postes"},
    ),
    "composants": Referentiel(
        Composant,
        ("reference",),
        {
            "designation": str, "type": str, "filetage": str, "matiere": str,
            "prix_unitaire_eur": float, "qte_min": int, "operation_id": str,
        },
        creation=True,
        champs_positifs=frozenset({"prix_unitaire_eur", "qte_min"}),
        cles_etrangeres={"operation_id": "operations"},
    ),
    "traitements": Referentiel(
        Traitement,
        ("id",),
        {
            "nom": str, "prix": float, "unite": str, "minimum_lot_eur": float,
            "delai_jours": int, "matieres_compatibles": str,
        },
        creation=True,
        champs_positifs=frozenset({"prix", "minimum_lot_eur"}),
    ),
    "parametres": Referentiel(Parametre, ("cle",), {"valeur": str}),
    "clients": Referentiel(
        Client,
        ("id",),
        {
            "nom": str, "secteur": str, "marge_specifique": float,
            "duree_conservation_plans_jours": int,
        },
        champs_positifs=frozenset({"duree_conservation_plans_jours"}),
    ),
    "bornes_controle": Referentiel(
        BorneControle,
        ("champ",),
        {"min": float, "max": float, "niveau": str, "message": str},
    ),
}


class ModificationAdmin(BaseModel):
    """Une modification proposée par l'IA, avec sa justification."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["mise_a_jour", "creation"]
    table: str
    ligne_id: str
    """Clé primaire sérialisée ; clé composite jointe par ``|`` (ex. ``S235JR|2.0``)."""
    champ: str | None = None
    """Champ modifié (mise à jour) ; None pour une création (``valeur`` = dict complet)."""
    valeur: Any
    justification: str = ""


class PropositionAdmin(BaseModel):
    """Réponse de l'agent : le diff proposé + remarque éventuelle."""

    model_config = ConfigDict(extra="forbid")

    modifications: list[ModificationAdmin] = Field(default_factory=list)
    remarque: str | None = None

    def ligne_avant_apres(self, session: Session) -> list[tuple[str, str, str, str, str]]:
        """Lignes d'affichage (table, ligne, champ, avant, après) + justification.

        La valeur actuelle est **lue en base** au moment de l'affichage.
        """
        lignes = []
        for modif in self.modifications:
            if modif.type == "creation":
                avant = "— (nouvelle ligne)"
                apres = str(modif.valeur)
                champ = "(création)"
            else:
                ligne = _trouver_ligne(modif.table, modif.ligne_id, session)
                champ = modif.champ or ""
                # Affichage arrondi par type de champ ; le stockage reste exact.
                avant = formater_valeur(champ, getattr(ligne, champ, None))
                apres = formater_valeur(champ, modif.valeur)
            lignes.append((modif.table, modif.ligne_id, champ, avant, apres))
        return lignes

    def appliquer(self, auteur: str, session: Session) -> int:
        """Applique le diff et écrit l'audit dans la même transaction.

        L'appelant commit ; un refus n'appelle jamais cette méthode. Chaque
        modification est **datée et attribuée** (§12).

        Returns:
            Le nombre de modifications appliquées.

        Raises:
            ErreurAdmin: re-validation avant écriture (la base a pu changer
                depuis la proposition).
        """
        for modif in self.modifications:
            _valider_modification(modif, session)
        for modif in self.modifications:
            referentiel = REFERENTIELS_MODIFIABLES[modif.table]
            if modif.type == "creation":
                valeurs = dict(modif.valeur)
                session.add(referentiel.modele(**valeurs))
                enregistrer_modification(
                    modif.table, modif.ligne_id, "(création)", None, str(modif.valeur),
                    auteur, session,
                )
            else:
                ligne = _trouver_ligne(modif.table, modif.ligne_id, session)
                ancienne = getattr(ligne, modif.champ)
                nouvelle = _coercer(modif.table, modif.champ, modif.valeur)
                setattr(ligne, modif.champ, nouvelle)
                enregistrer_modification(
                    modif.table, modif.ligne_id, modif.champ, ancienne, nouvelle,
                    auteur, session,
                )
        return len(self.modifications)


def _trouver_ligne(table: str, ligne_id: str, session: Session):
    """Retrouve la ligne par sa clé (simple ou composite jointe par ``|``)."""
    referentiel = REFERENTIELS_MODIFIABLES[table]
    segments = ligne_id.split("|")
    if len(segments) != len(referentiel.pk):
        msg = f"Clé {ligne_id!r} invalide pour {table} ({len(referentiel.pk)} colonnes attendues)."
        raise ErreurAdmin(msg)
    valeurs = {}
    for colonne, segment in zip(referentiel.pk, segments, strict=True):
        try:
            python_type = referentiel.modele.__table__.c[colonne].type.python_type
            valeurs[colonne] = python_type(segment)
        except (ValueError, TypeError) as e:
            msg = f"Segment de clé {segment!r} incompatible avec {table}.{colonne}."
            raise ErreurAdmin(msg) from e
    ligne = session.get(referentiel.modele, valeurs)
    if ligne is None:
        msg = f"Ligne introuvable : {table} « {ligne_id} »."
        raise ErreurAdmin(msg)
    return ligne


def _coercer(table: str, champ: str, valeur: Any) -> Any:
    type_attendu = REFERENTIELS_MODIFIABLES[table].champs[champ]
    if type_attendu is bool:
        # bool("false") vaut True : les chaînes sont gérées explicitement.
        if isinstance(valeur, str):
            if valeur.lower() in ("true", "vrai", "oui", "1"):
                return True
            if valeur.lower() in ("false", "faux", "non", "0"):
                return False
            msg = f"Valeur incompatible pour {table}.{champ} : {valeur!r}."
            raise ErreurAdmin(msg)
        return bool(valeur)
    try:
        return type_attendu(valeur)
    except (TypeError, ValueError) as e:
        msg = f"Valeur incompatible pour {table}.{champ} : {valeur!r}."
        raise ErreurAdmin(msg) from e


def _valider_modification(modif: ModificationAdmin, session: Session) -> None:
    """Validation métier d'une modification avant toute écriture."""
    referentiel = REFERENTIELS_MODIFIABLES.get(modif.table)
    if referentiel is None:
        msg = f"Table non administrable : {modif.table!r}."
        raise ErreurAdmin(msg)
    if modif.champ in referentiel.pk:
        msg = f"La clé primaire {modif.table}.{modif.champ} n'est pas modifiable."
        raise ErreurAdmin(msg)

    if modif.type == "creation":
        if not referentiel.creation:
            msg = f"Création refusée en V1 sur {modif.table}."
            raise ErreurAdmin(msg)
        if not isinstance(modif.valeur, dict):
            msg = "Une création attend un objet complet de la ligne."
            raise ErreurAdmin(msg)
        cles_manquantes = [c for c in referentiel.pk if c not in modif.valeur]
        if cles_manquantes:
            msg = f"Clé primaire absente de la création : {cles_manquantes}."
            raise ErreurAdmin(msg)
        for champ, valeur in modif.valeur.items():
            if champ not in referentiel.champs and champ not in referentiel.pk:
                msg = f"Champ hors whitelist : {modif.table}.{champ}."
                raise ErreurAdmin(msg)
            if champ in referentiel.champs:
                valeur = _coercer(modif.table, champ, valeur)
            _valider_valeur(referentiel, modif.table, champ, valeur, session)
        # La clé ne doit pas être déjà prise.
        try:
            _trouver_ligne(modif.table, modif.ligne_id, session)
            msg = f"La clé {modif.ligne_id!r} existe déjà dans {modif.table}."
            raise ErreurAdmin(msg)
        except ErreurAdmin as e:
            if "introuvable" not in str(e):
                raise
        return

    # Mise à jour
    if modif.champ is None:
        msg = "Une mise à jour exige un champ."
        raise ErreurAdmin(msg)
    if modif.champ not in referentiel.champs:
        msg = f"Champ hors whitelist : {modif.table}.{modif.champ}."
        raise ErreurAdmin(msg)
    ligne = _trouver_ligne(modif.table, modif.ligne_id, session)
    del ligne  # l'existence est vérifiée ; la lecture sert à l'avant/après
    valeur = _coercer(modif.table, modif.champ, modif.valeur)
    _valider_valeur(referentiel, modif.table, modif.champ, valeur, session)


def _valider_valeur(
    referentiel: Referentiel, table: str, champ: str, valeur: Any, session: Session
) -> None:
    if champ in referentiel.champs_positifs and valeur <= 0:
        msg = f"{table}.{champ} doit être strictement positif ({valeur!r})."
        raise ErreurAdmin(msg)
    table_fk = referentiel.cles_etrangeres.get(champ)
    if table_fk and valeur is not None:
        ref = REFERENTIELS_MODIFIABLES[table_fk]
        if session.get(ref.modele, {ref.pk[0]: str(valeur)}) is None:
            msg = f"Clé étrangère inconnue : {table}.{champ} = {valeur!r} (table {table_fk})."
            raise ErreurAdmin(msg)


def proposer_modifications(texte: str, nom_modele: str, session: Session) -> PropositionAdmin:
    """Demande à l'IA un diff de mise à jour des référentiels.

    Args:
        texte: instruction en texte libre (« le S235JR passe à 1,25 €/kg »).
        nom_modele: désignation du modèle (``llm.creer_modele``).
        session: session SQLAlchemy (validation métier sur l'état actuel).

    Returns:
        La proposition validée (whitelist + métier) — aucune écriture.

    Raises:
        ErreurAdmin: texte vide, réponse illisible ou diff invalide.
    """
    if not texte.strip():
        msg = "Décrivez la mise à jour à effectuer."
        raise ErreurAdmin(msg)
    modele = creer_modele(nom_modele)
    try:
        reponse = modele.generer(prompt_systeme_admin(), prompt_utilisateur_admin(texte), [])
    except ErreurModele as e:
        msg = f"Agent indisponible : {e}"
        raise ErreurAdmin(msg) from e
    try:
        proposition = PropositionAdmin.model_validate_json(extraire_json(reponse.texte))
    except (ValidationError, ValueError) as e:
        msg = "Réponse de l'agent illisible — reformulez la demande."
        raise ErreurAdmin(msg) from e
    for modif in proposition.modifications:
        _valider_modification(modif, session)
    return proposition
