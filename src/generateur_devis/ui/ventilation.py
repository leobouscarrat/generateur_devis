"""Ventilation des coûts pour l'écran de validation : d'où vient chaque euro.

Toutes les données sont déjà calculées et figées dans ``Chiffrage`` (blocs +
trace, architecture §Étape 5) — ce module ne fait que les mettre en forme
pour l'affichage. Logique pure, testable sans Streamlit.
"""

from __future__ import annotations

from generateur_devis.calcul_prix import Chiffrage
from generateur_devis.ui.formatage import formater_valeur


def ventilation_couts(chiffrage: Chiffrage) -> list[dict[str, str]]:
    """Une ligne par bloc de coût : variable (€/pièce), fixe (€/lot), détail.

    La règle d'agrégation (§4) est rappelée dans l'écran :
    coût(Q) = Σ variables + Σ fixes ÷ Q, finition = max(variable, fixe ÷ Q),
    prix = coût ÷ (1 − marge).
    """
    b = chiffrage.blocs_1_3
    b46 = chiffrage.blocs_4_6
    lignes = [
        {
            "bloc": "Matière",
            "variable_eur_piece": b.matiere.cout_variable_eur,
            "fixe_eur_lot": b.matiere.cout_fixe_eur_par_lot,
            "detail": (
                f"{formater_valeur('masse_kg', b.matiere.masse_flan_kg)} kg "
                f"× {formater_valeur('prix_eur_kg', b.matiere.prix_matiere_eur_kg)} €/kg "
                f"(rendement calepinage {b.matiere.rendement_calepinage:.0%})"
            ),
        },
        {
            "bloc": "Découpe",
            "variable_eur_piece": b.decoupe.cout_variable_eur,
            "fixe_eur_lot": b.decoupe.cout_fixe_eur_par_lot,
            "detail": (
                f"{formater_valeur('longueur_mm', b.decoupe.longueur_coupe_mm)} mm de coupe, "
                f"{b.decoupe.nombre_amorcages} amorçage(s), "
                f"{formater_valeur('taux_horaire_eur_h', b.decoupe.taux_horaire_eur_h)} €/h"
            ),
        },
        {
            "bloc": "Pliage",
            "variable_eur_piece": b.pliage.cout_variable_eur,
            "fixe_eur_lot": b.pliage.cout_fixe_eur_par_lot,
            "detail": (
                f"{b.pliage.nb_plis} pli(s) × "
                f"{formater_valeur('temps_s', b.pliage.temps_par_pli_s)} s, "
                f"{formater_valeur('taux_horaire_eur_h', b.pliage.taux_horaire_eur_h)} €/h"
            ),
        },
    ]
    if b46.soudure.cout_variable_eur or b46.soudure.cout_fixe_eur_par_lot:
        lignes.append({
            "bloc": "Soudure",
            "variable_eur_piece": b46.soudure.cout_variable_eur,
            "fixe_eur_lot": b46.soudure.cout_fixe_eur_par_lot,
            "detail": "assemblage",
        })
    if b46.finition is not None:
        lignes.append({
            "bloc": "Finition",
            "variable_eur_piece": b46.finition.cout_variable_eur,
            "fixe_eur_lot": b46.finition.cout_fixe_eur_par_lot,
            "detail": (
                f"{b46.finition.traitement_id} — "
                f"{formater_valeur('surface_m2', b46.finition.surface_traitee_m2)} m² "
                f"(minimum de lot {formater_valeur('cout_unitaire_eur', b46.finition.minimum_lot_eur)} €)"
            ),
        })
    if b46.composants.cout_variable_eur or b46.composants.cout_fixe_eur_par_lot:
        lignes.append({
            "bloc": "Composants & opérations",
            "variable_eur_piece": b46.composants.cout_variable_eur,
            "fixe_eur_lot": b46.composants.cout_fixe_eur_par_lot,
            "detail": (
                f"composants {formater_valeur('cout_unitaire_eur', b46.composants.cout_composants_eur)} €, "
                f"opérations {formater_valeur('cout_unitaire_eur', b46.composants.cout_operations_eur)} € "
                f"({', '.join(b46.composants.postes_utilises)})"
            ),
        })
    return lignes


def lignes_trace(chiffrage: Chiffrage) -> list[dict[str, str]]:
    """Trace détaillée du calcul : bloc, formule, valeurs, origine des données."""
    return [
        {
            "bloc": ligne.bloc,
            "formule": ligne.formule,
            "valeurs": ", ".join(f"{k}={v}" for k, v in ligne.valeurs.items()),
            "origine": ligne.table_origine,
            "date_prix": str(ligne.date_prix) if ligne.date_prix else "—",
        }
        for ligne in chiffrage.trace
    ]
