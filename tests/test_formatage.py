"""Tests du formateur de précision d'affichage (issue #34)."""

from generateur_devis.ui.formatage import formater_valeur


def test_prix_deux_decimales():
    assert formater_valeur("prix_eur_kg", 1.1) == "1.10"
    assert formater_valeur("taux_horaire_eur_h", 120) == "120.00"
    assert formater_valeur("minimum_lot_eur", 0.256) == "0.26"


def test_ratios_trois_decimales():
    assert formater_valeur("marge_specifique", 0.25) == "0.250"
    assert formater_valeur("densite_kg_dm3", 7.85) == "7.850"


def test_suffixes():
    assert formater_valeur("epaisseur_mm", 2.0) == "2.00"  # suffixe _mm
    assert formater_valeur("temps_par_pli_s", 12.345) == "12.35"  # suffixe _s
    assert formater_valeur("temps_reglage_min", 15.0) == "15.00"  # suffixe _min


def test_entiers():
    assert formater_valeur("qte_min", 1.9) == "2"
    assert formater_valeur("nb_operateurs", 1) == "1"
    assert formater_valeur("quantite", 4) == "4"  # #67 : pas « 4.00 »


def test_non_numeriques():
    assert formater_valeur("designation", "Écrou M6") == "Écrou M6"
    assert formater_valeur("en_stock", True) == "oui"
    assert formater_valeur("en_stock", False) == "non"
    assert formater_valeur("secteur", None) == "—"
