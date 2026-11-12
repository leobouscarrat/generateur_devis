"""Précision d'affichage par type de champ (issue #34 ; migration générale en 5.3).

Règle : les valeurs sont **stockées exactes** (jamais arrondies en base ni
dans l'audit) et **arrondies uniquement à l'affichage**, selon le type de
champ. La 5.3 remplacera les formats ad hoc (`:.2f`, `round(x, 2)`) des
affichages existants par ce formateur.
"""

from __future__ import annotations

from typing import Any

PRECISION_PAR_SUFFIXE: dict[str, int] = {
    # Prix et coûts : 2 décimales (le prix final est à 2 décimales maximum).
    "_eur": 2,
    "prix_eur_kg": 2,
    "prix_unitaire_eur": 2,
    "prix_unitaire_eur_h": 2,
    "taux_horaire_eur_h": 2,
    "minimum_lot_eur": 2,
    "surcout_pct": 2,
    # Ratios (rendements, marges) : 3 décimales (0,25 vs 0,3 c'est large).
    "marge_specifique": 3,
    "densite_kg_dm3": 3,
    # Longueurs et épaisseurs (mm) : 2 décimales.
    "_mm": 2,
    # Temps : 2 décimales.
    "_s": 2,
    "_min": 2,
    # Entiers naturels : quantités, opérateurs, délais.
    "quantite": 0,
    "qte_min": 0,
    "nb_operateurs": 0,
    "delai_jours": 0,
    "duree_conservation_plans_jours": 0,
    "dim_max_mm": 0,
}

PRECISION_DEFAUT = 2
"""Décimales pour un champ numérique sans règle explicite."""


def formater_valeur(champ: str, valeur: Any) -> str:
    """Formate une valeur pour l'affichage selon le type de champ.

    Args:
        champ: nom du champ (ex. ``prix_eur_kg``, ``temps_par_pli_s``).
        valeur: valeur à afficher (stockée exacte — l'arrondi est ici).

    Returns:
        Texte formaté ; les non-numériques passent par ``str``.
    """
    if valeur is None:
        return "—"
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if not isinstance(valeur, (int, float)):
        return str(valeur)
    precision = PRECISION_PAR_SUFFIXE.get(champ)
    if precision is None:
        for suffixe, decimales in PRECISION_PAR_SUFFIXE.items():
            if suffixe.startswith("_") and champ.endswith(suffixe):
                precision = decimales
                break
    if precision is None:
        precision = PRECISION_DEFAUT
    if precision == 0:
        return f"{valeur:.0f}"
    return f"{valeur:.{precision}f}"
