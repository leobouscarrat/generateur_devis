"""Consultation en lecture seule des référentiels administrables (issue #94).

L'administrateur doit connaître la valeur en vigueur avant de demander une mise
à jour à l'agent. Consultation **déterministe, sans IA** : on montre exactement
ce que l'agent peut changer (clé primaire + champs de la whitelist
``REFERENTIELS_MODIFIABLES``), lignes triées par clé, valeurs arrondies à
l'affichage seulement par `formater_valeur`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from generateur_devis.admin_agent import REFERENTIELS_MODIFIABLES, Referentiel
from generateur_devis.ui.formatage import formater_valeur

LIBELLES_TABLES: dict[str, str] = {
    "matieres": "Matières",
    "epaisseurs_dispo": "Épaisseurs disponibles",
    "postes": "Postes et taux horaires",
    "vitesses_coupe": "Vitesses de coupe",
    "temps_pliage": "Temps de pliage",
    "operations": "Opérations secondaires",
    "composants": "Composants",
    "traitements": "Traitements de surface",
    "parametres": "Paramètres",
    "clients": "Clients",
    "bornes_controle": "Bornes de contrôle",
}
"""Table administrable → libellé de la liste déroulante (clés = la whitelist)."""


def _referentiel(table: str) -> Referentiel:
    try:
        return REFERENTIELS_MODIFIABLES[table]
    except KeyError:
        msg = f"Table non consultable : {table!r} (hors référentiels administrables)."
        raise ValueError(msg) from None


def colonnes_consultables(table: str) -> list[str]:
    """Colonnes affichées : clé primaire puis champs modifiables, rien d'autre.

    Raises:
        ValueError: table hors ``REFERENTIELS_MODIFIABLES`` (ex. ``historique_devis``).
    """
    referentiel = _referentiel(table)
    return [*referentiel.pk, *referentiel.champs]


def consulter_referentiel(table: str, session: Session) -> list[dict[str, str]]:
    """Lignes d'une table administrable, triées par clé, formatées pour l'affichage.

    Returns:
        Une entrée ``{colonne: texte}`` par ligne, colonnes dans l'ordre de
        `colonnes_consultables` ; liste vide si la table est vide. Lecture seule.

    Raises:
        ValueError: table hors ``REFERENTIELS_MODIFIABLES``.
    """
    referentiel = _referentiel(table)
    colonnes = colonnes_consultables(table)
    tri = [referentiel.modele.__table__.c[c] for c in referentiel.pk]
    return [
        {c: formater_valeur(c, getattr(ligne, c)) for c in colonnes}
        for ligne in session.scalars(select(referentiel.modele).order_by(*tri))
    ]
