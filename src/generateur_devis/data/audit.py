"""Audit des modifications de référentiels (issue #33, architecture §12).

Toute modification d'un référentiel (matières, postes, bornes, clients…) est
**datée et attribuée** : jamais de modification anonyme. Ces fonctions pures
sont le seul point d'entrée d'écriture de l'audit — l'agent d'administration
(5.2) les appelle dans la même transaction que l'écriture métier.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from generateur_devis.data.tables import ModificationReferentiel


class ErreurAudit(ValueError):
    """Enregistrement d'audit invalide (ex. auteur manquant)."""


def _serialiser(valeur: Any) -> str | None:
    """Sérialisation exacte : l'audit conserve la valeur, l'affichage arrondit.

    Les floats passent par ``repr`` (17 chiffres significatifs — 1.10 reste
    1.1 mais 0.30000000000000004 reste exact).
    """
    if valeur is None:
        return None
    if isinstance(valeur, float):
        return repr(valeur)
    return str(valeur)


def enregistrer_modification(
    table_nom: str,
    ligne_id: str,
    champ: str,
    avant: Any,
    apres: Any,
    auteur: str,
    session: Session,
) -> ModificationReferentiel:
    """Enregistre une ligne d'audit pour une modification de référentiel.

    Args:
        table_nom: table ciblée (ex. ``"matieres"``).
        ligne_id: identifiant de la ligne modifiée (clé primaire).
        champ: champ modifié (ex. ``"prix_kg_eur"``).
        avant: valeur avant modification — None pour une création.
        apres: valeur après modification — None pour une suppression.
        auteur: auteur de la modification (obligatoire : §12, attribuée).
        session: session SQLAlchemy — la ligne est ajoutée, **non commitée**
            (l'appelant orchestre la transaction avec l'écriture métier).

    Returns:
        La ligne d'audit créée.

    Raises:
        ErreurAudit: auteur vide (jamais de modification anonyme).
    """
    if not auteur or not auteur.strip():
        msg = "Auteur obligatoire : jamais de modification anonyme (§12)."
        raise ErreurAudit(msg)
    ligne = ModificationReferentiel(
        table_nom=table_nom,
        ligne_id=ligne_id,
        champ=champ,
        valeur_avant=_serialiser(avant),
        valeur_apres=_serialiser(apres),
        auteur=auteur.strip(),
    )
    session.add(ligne)
    session.flush()  # id attribué sans commit
    return ligne


def historique(
    session: Session,
    table_nom: str | None = None,
    ligne_id: str | None = None,
) -> list[ModificationReferentiel]:
    """Lit l'historique des modifications, le plus récent d'abord.

    Args:
        session: session SQLAlchemy.
        table_nom: filtre sur la table (None = toutes).
        ligne_id: filtre sur la ligne (None = toutes les lignes).

    Returns:
        Les lignes d'audit, triées par date décroissante.
    """
    requete = select(ModificationReferentiel).order_by(ModificationReferentiel.date.desc())
    if table_nom is not None:
        requete = requete.where(ModificationReferentiel.table_nom == table_nom)
    if ligne_id is not None:
        requete = requete.where(ModificationReferentiel.ligne_id == ligne_id)
    return list(session.scalars(requete))
