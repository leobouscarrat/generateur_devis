"""Tests du schéma SQLite des référentiels de coût (étape 1.1)."""

from sqlalchemy import create_engine, inspect

from generateur_devis.data.tables import Base

TABLES_ATTENDUES = {
    "matieres",
    "epaisseurs_dispo",
    "postes",
    "vitesses_coupe",
    "temps_pliage",
    "operations",
    "composants",
    "traitements",
    "parametres",
    "clients",
    "historique_devis",
    "bornes_controle",
}

COLONNES_CONFIDENTIALITE_CLIENTS = {
    "ia_externe_autorisee",
    "reutilisation_autorisee",
    "duree_conservation_plans_jours",
    "suppression_si_refus",
}


def _inspecteur():
    """Crée le schéma sur une base SQLite en mémoire et renvoie un inspecteur."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return inspect(engine)


def test_les_12_tables_de_reference_existent():
    assert set(_inspecteur().get_table_names()) == TABLES_ATTENDUES


def test_clients_porte_les_colonnes_de_confidentialite():
    """Architecture §11.3 : réglages de conservation et d'usage IA par client."""
    colonnes = {c["name"] for c in _inspecteur().get_columns("clients")}
    assert COLONNES_CONFIDENTIALITE_CLIENTS <= colonnes


def test_vitesses_coupe_a_une_cle_composite():
    """Une vitesse est identifiée par (poste, famille de matière, épaisseur)."""
    pk = _inspecteur().get_pk_constraint("vitesses_coupe")
    assert set(pk["constrained_columns"]) == {"poste_id", "famille", "epaisseur_mm"}


def test_epaisseurs_dispo_a_une_cle_composite():
    """Une ligne par couple matière × épaisseur (sources_donnees.md §2.2)."""
    pk = _inspecteur().get_pk_constraint("epaisseurs_dispo")
    assert set(pk["constrained_columns"]) == {"matiere_id", "epaisseur_mm"}


def test_colonnes_obligatoires_matieres():
    colonnes = {c["name"]: c for c in _inspecteur().get_columns("matieres")}
    for nom in ("id", "famille", "densite_kg_dm3", "prix_eur_kg"):
        assert not colonnes[nom]["nullable"], f"{nom} doit être NOT NULL"


def test_parametres_valeur_est_en_texte():
    """valeur stocke du texte (« 0.25 », « 1,10,100,1000 », « EUR ») ;
    le typage est fait à la lecture par la couche Pydantic (sources_donnees.md §2.9)."""
    colonnes = {c["name"]: c for c in _inspecteur().get_columns("parametres")}
    assert not colonnes["valeur"]["nullable"]
    assert str(colonnes["valeur"]["type"]) == "VARCHAR"
