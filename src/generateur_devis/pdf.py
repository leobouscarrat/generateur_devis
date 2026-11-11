"""Génération du PDF client à l'émission (issue #26, architecture §6/§9).

Vue **client** uniquement : désignation, matière, prix et quantités — les
coûts, la marge et le tracé de calcul ne sortent **jamais** (§6).

Fonction pure : pas d'I/O, pas de Streamlit ; retourne les bytes du PDF.
"""

from __future__ import annotations

from datetime import timedelta

from fpdf import FPDF

from generateur_devis.devis import Devis


def _prix_unitaire_option(prix: float, minimum_lot_eur: float, quantite: int) -> float:
    """Option chiffrée à part : max(variable, minimum de lot ÷ Q) (logique §3.3)."""
    return max(prix, minimum_lot_eur / quantite)


def _ligne(pdf: FPDF, libelle: str, valeur: str) -> None:
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(60, 7, libelle)
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 7, valeur, new_x="LMARGIN", new_y="NEXT")


def generer_pdf_client(devis: Devis, validite_jours: int, conditions: str) -> bytes:
    """Génère le PDF de la vue client d'un devis.

    Args:
        devis: devis validé ou émis (les prix sont figés à la validation).
        validite_jours: durée de validité (paramètre ``validite_devis_jours``
            — aucune valeur en dur, fournie par l'appelant).
        conditions: conditions générales (paramètre ``conditions_generales``).

    Returns:
        Le contenu du PDF en bytes.
    """
    piece = devis.piece_validee
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- En-tête --------------------------------------------------------------
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, f"Devis {devis.id}", new_x="LMARGIN", new_y="NEXT")
    date_emission = devis.date_emission or devis.date_creation
    _ligne(pdf, "Date :", date_emission.strftime("%d/%m/%Y"))
    _ligne(
        pdf,
        "Validité :",
        (date_emission + timedelta(days=validite_jours)).strftime("%d/%m/%Y")
        + f" ({validite_jours} jours)",
    )
    if devis.client_id:
        _ligne(pdf, "Client :", devis.client_id)
    pdf.ln(4)

    # --- Pièce -----------------------------------------------------------------
    pdf.set_font("helvetica", "B", 13)
    pdf.cell(0, 8, "Pièce", new_x="LMARGIN", new_y="NEXT")
    _ligne(pdf, "Désignation :", piece.identification.designation.valeur or "Pièce")
    if piece.identification.reference.valeur:
        _ligne(pdf, "Référence :", piece.identification.reference.valeur)
    matiere = piece.matiere.designation.valeur or devis.matiere_id
    epaisseur = piece.matiere.epaisseur.valeur
    _ligne(pdf, "Matière :", f"{matiere}" + (f", {epaisseur:g} mm" if epaisseur else ""))
    pdf.ln(4)

    # --- Prix par palier de quantité -------------------------------------------
    pdf.set_font("helvetica", "B", 13)
    pdf.cell(0, 8, "Prix", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(50, 8, "Quantité", border=1)
    pdf.cell(60, 8, "Prix unitaire", border=1)
    pdf.cell(60, 8, "Prix total", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    for palier in devis.chiffrage.paliers:
        pdf.cell(50, 8, f"{palier.quantite}", border=1)
        pdf.cell(60, 8, f"{palier.prix_unitaire_eur:.2f} EUR", border=1)
        pdf.cell(
            60,
            8,
            f"{palier.prix_unitaire_eur * palier.quantite:.2f} EUR",
            border=1,
            new_x="LMARGIN",
            new_y="NEXT",
        )

    # --- Options chiffrées à part (§6 : ex. peinture proposée) ------------------
    if devis.options:
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 8, "Options (chiffrées à part)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 11)
        for option in devis.options:
            prix = _prix_unitaire_option(
                option.prix, option.minimum_lot_eur, devis.quantite_commandee
            )
            pdf.cell(
                0,
                7,
                f"- {option.traitement_id} : {prix:.2f} EUR/pièce "
                f"(quantité {devis.quantite_commandee})",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    # --- Conditions générales ----------------------------------------------------
    pdf.ln(4)
    pdf.set_font("helvetica", "I", 9)
    pdf.multi_cell(0, 5, conditions)

    return bytes(pdf.output())
