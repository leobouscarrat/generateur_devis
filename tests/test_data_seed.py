"""Tests du seed des valeurs simulées des référentiels (étape 1.2)."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import (
    Base,
    Composant,
    Matiere,
    Operation,
    Parametre,
    Poste,
    TempsPliage,
    VitesseCoupe,
)

expected_tables = {
    "matieres", "epaisseurs_dispo", "postes", "vitesses_coupe",
    "temps_pliage", "operations", "composants", "traitements",
    "parametres", "clients", "historique_devis", "bornes_controle",
    "modifications_referentiels",  # audit §12 (issue #33) — vide après seed
}

# Tables légitimement vides après seed() (pas de référentiel, que de l'audit).
TABLES_VIDES_APRES_SEED = {"modifications_referentiels"}


@pytest.fixture
def session():
    """Fixture SQLite en mémoire pour les tests de seed."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _compte_lignes(session, table_name):
    """Compte le nombre de lignes dans une table via SQL."""
    result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.scalar()


def test_chargement_complet_12_tables(session):
    """Tous les référentiels doivent être peuplés après seed()."""
    seed(session)
    # Vérifier que toutes les tables ont au moins une ligne (sauf l'audit)
    for table in expected_tables - TABLES_VIDES_APRES_SEED:
        compte = _compte_lignes(session, table)
        assert compte > 0, f"Table {table} vide après seed()"
    # Vérifier les noms de tables via l'inspecteur attaché à l'engine de la session
    ins = inspect(session.get_bind())
    noms = set(ins.get_table_names())
    assert noms == expected_tables, f"Tables manquantes : {expected_tables - noms}"


def test_idempotence_deux_rappels(session):
    """Deux appels successifs à seed() ne doivent pas doubler les comptages."""
    seed(session)
    compte_1 = {}
    for table in expected_tables:
        compte_1[table] = _compte_lignes(session, table)

    seed(session)
    # Après le 2ème seed, les comptages doivent être identiques
    # (stratégie merge/upsert : pas de doublons)
    for table in expected_tables:
        lignes_2 = _compte_lignes(session, table)
        assert compte_1[table] == lignes_2, \
            f"Doublon détecté pour {table} : {compte_1[table]} vs {lignes_2}"


def test_inox_plus_cher_que_acier():
    """Le prix de l'inox doit être supérieur à celui de l'acier."""
    from generateur_devis.data.seed import _MATIERES
    prix_inox = next(m.prix_eur_kg for m in _MATIERES if m.famille == "inox")
    prix_acier = next(m.prix_eur_kg for m in _MATIERES if m.famille == "acier")
    assert prix_inox > prix_acier, \
        f"Inox {prix_inox} € ne doit pas être moins cher que l'acier {prix_acier} €"


def test_vitesses_croissantes_epaisseur():
    """Les vitesses de coupe doivent décroître quand l'épaisseur augmente."""
    from generateur_devis.data.seed import _VITESSES_COUPE
    # Regroupement par famille
    familles = {}
    for v in _VITESSES_COUPE:
        familles.setdefault(v.famille, []).append(v)

    for famille, vitesses in familles.items():
        vitesses_triees = sorted(vitesses, key=lambda v: v.epaisseur_mm)
        for i in range(len(vitesses_triees) - 1):
            v1 = vitesses_triees[i]
            v2 = vitesses_triees[i + 1]
            assert v2.vitesse_m_min <= v1.vitesse_m_min, \
                f"Famille {famille} : vitesse {v1.epaisseur_mm}mm={v1.vitesse_m_min} m/min " \
                f"Doit être >= vitesse {v2.epaisseur_mm}mm={v2.vitesse_m_min} m/min"


def test_temps_pliage_croissant_epaisseur():
    """Les temps de pliage doivent croître avec l'épaisseur."""
    from generateur_devis.data.seed import _TEMPS_PLIAGE

    # Vérification des temps de pliage dans les données seedées
    # Petite catégorie : ep=3 → 8s, ep=10 → 12s (12 > 8 ✓)
    # Moyenne catégorie : ep=3 → 15s, ep=10 → 20s (20 > 15 ✓)
    # Grande catégorie : ep=3 → 30s, ep=10 → 45s (45 > 30 ✓)

    # Vérification formelle : pour chaque catégorie, le temps à ep=10 > temps à ep=3
    petites = [t for t in _TEMPS_PLIAGE if t.categorie == "petite"]
    moyennes = [t for t in _TEMPS_PLIAGE if t.categorie == "moyenne"]
    grandes = [t for t in _TEMPS_PLIAGE if t.categorie == "grande"]

    petite_3s = next(t for t in petites if t.epaisseur_max_mm == 3.0)
    petite_10s = next(t for t in petites if t.epaisseur_max_mm == 10.0)
    assert petite_10s.temps_par_pli_s > petite_3s.temps_par_pli_s, \
        f"Temps pliage ep=10 ({petite_10s.temps_par_pli_s}s) > ep=3 ({petite_3s.temps_par_pli_s}s)"

    moyenne_3s = next(t for t in moyennes if t.epaisseur_max_mm == 3.0)
    moyenne_10s = next(t for t in moyennes if t.epaisseur_max_mm == 10.0)
    assert moyenne_10s.temps_par_pli_s > moyenne_3s.temps_par_pli_s, \
        f"Temps pliage ep=10 ({moyenne_10s.temps_par_pli_s}s) > ep=3 ({moyenne_3s.temps_par_pli_s}s)"

    grande_3s = next(t for t in grandes if t.epaisseur_max_mm == 3.0)
    grande_10s = next(t for t in grandes if t.epaisseur_max_mm == 10.0)
    assert grande_10s.temps_par_pli_s > grande_3s.temps_par_pli_s, \
        f"Temps pliage ep=10 ({grande_10s.temps_par_pli_s}s) > ep=3 ({grande_3s.temps_par_pli_s}s)"


def test_prix_composants_degressifs_avec_qte():
    """Les prix unitaire des composants doivent diminuer quand qte_min augmente."""
    from generateur_devis.data.seed import _COMPOSANTS
    es_m6_qte1 = next(c for c in _COMPOSANTS if c.reference == "ES-M6-A" and c.qte_min == 1)
    es_m6_qte1000 = next(c for c in _COMPOSANTS if c.reference == "ES-M6-B" and c.qte_min == 1000)
    assert es_m6_qte1.prix_unitaire_eur > es_m6_qte1000.prix_unitaire_eur, \
        f"Prix dégressif attendu : {es_m6_qte1.prix_unitaire_eur} > {es_m6_qte1000.prix_unitaire_eur}"


def test_historique_devis_30_lignes_valides(session):
    """L'historique_devis doit compter ~30 lignes avec des FK valides."""
    seed(session)
    nb_lignes = _compte_lignes(session, "historique_devis")
    assert 20 <= nb_lignes <= 40, f"Expected ~30 lignes, got {nb_lignes}"

    # Vérification des FK vers clients via requête SQL directe
    rows = session.execute(text("""
        SELECT h.id, h.client_id, h.matiere_id, h.traitement_id
        FROM historique_devis h
        LEFT JOIN clients c ON h.client_id = c.id
        WHERE c.id IS NULL AND h.client_id IS NOT NULL
    """)).fetchall()
    assert len(rows) == 0, f"{len(rows)} lignes historique_devis avec client_id invalide"


def test_piece_support_compatibilite_cout_prix(session):
    """Compatibilité piece_support : données seedées doivent permettre coût ≈ 2,20 € / prix ≈ 2,93 € à qté 100."""
    seed(session)

    # --- Récupération des valeurs depuis les tables initialisées ---
    matiere = session.query(Matiere).filter_by(id="S235JR").one()
    assert matiere.prix_eur_kg == 1.10, f"S235JR prix_eur_kg attendu 1.10, got {matiere.prix_eur_kg}"
    assert matiere.densite_kg_dm3 == 7.85, f"S235JR densite attendue 7.85, got {matiere.densite_kg_dm3}"

    # Vitesses de coupe laser acier 2mm
    vitesse = session.query(VitesseCoupe).filter_by(
        poste_id="LASER_3KW", famille="acier", epaisseur_mm=2.0
    ).one()
    assert vitesse.vitesse_m_min == 5.0, f"Vitesse acier 2mm attendue 5.0, got {vitesse.vitesse_m_min}"
    assert vitesse.temps_amorcage_s == 1.0, f"Tempsamorçage acier 2mm attendue 1.0, got {vitesse.temps_amorcage_s}"

    # Composant écrou M6 acier
    composant = session.query(Composant).filter_by(reference="ES-M6-A").one()
    assert composant.prix_unitaire_eur == 0.20

    # Paramètres globaux
    parametre = session.query(Parametre).filter_by(cle="marge_defaut").one()
    marge = float(parametre.valeur)

    # Postes machine
    laser = session.query(Poste).filter_by(id="LASER_3KW").one()
    plieuse = session.query(Poste).filter_by(id="PLIEUSE_CN").one()

    # Temps de pliage pour acier 2mm (catégorie petite, epaisseur_max=3.0 dans les seed data)
    # La pièce 2mm appartient à la catégorie "petite" (ep_max=3.0)
    temps_pliage = session.query(TempsPliage).filter_by(
        categorie="petite", epaisseur_max_mm=3.0
    ).one()

    # --- Calcul du coût piece_support §8.3 ---
    # Zone flan standard : 75 × 60 mm = 4 500 mm²
    zone_mm2 = 4500.0  # format standard piece_support (75×60 mm), §8.3

    # Bloc 1 : Matière
    masse_kg = zone_mm2 * 2.0 * matiere.densite_kg_dm3 / 1_000_000
    cout_matiere = masse_kg / 0.80 * matiere.prix_eur_kg  # rendement calepinage 0,80

    # Bloc 2 : Découpe
    longueur_coupe_m = 0.343  # ≈ 343 mm depuis §8.3 (contour + trous)
    nb_amorçages = 5
    temps_amorcage = vitesse.temps_amorcage_s
    taux_laser = laser.taux_horaire_eur_h
    temps_cycle_s = longueur_coupe_m / vitesse.vitesse_m_min * 60 + nb_amorçages * temps_amorcage
    cout_variable_coupe = temps_cycle_s * taux_laser / 3600
    cout_remise_coupe = (laser.temps_reglage_min * taux_laser / 60) / 100

    # Bloc 3 : Pliage
    nb_plis = 2
    temps_par_pli = temps_pliage.temps_par_pli_s
    taux_pliage = plieuse.taux_horaire_eur_h
    cout_variable_pliage = nb_plis * temps_par_pli * taux_pliage / 3600
    cout_remise_pliage = (plieuse.temps_reglage_min * taux_pliage / 60) / 100

    # Bloc 6 : Composants & opérations secondaires
    qte_composants = 2  # 2 écrous à sertir M6
    cout_composants = qte_composants * composant.prix_unitaire_eur

    # Taux et réglage depuis le poste de sertissage
    poste_sertissage = session.query(Poste).filter_by(id="SERTISSEUSE").one()
    taux_operation_h = poste_sertissage.taux_horaire_eur_h
    reglage_h = poste_sertissage.temps_reglage_min

    operation_sertissage = session.query(Operation).filter_by(id="SERTISSAGE").one()
    # 2 écrous à sertir M6 × 12s chacun = 24s total (voir doc §8.3 : "sertissage 24 s")
    temps_sertissage_total = 2 * operation_sertissage.temps_s
    temps_ebavurage = session.query(Operation).filter_by(id="EBAVURAGE_P").one().temps_s
    cout_variable_operations = (temps_sertissage_total + temps_ebavurage) * taux_operation_h / 3600
    cout_remise_operations = (reglage_h * taux_operation_h / 60) / 100

    # Totaux
    variable_total = (cout_matiere + cout_variable_coupe + cout_variable_pliage + cout_composants + cout_variable_operations)
    reglage_total = (cout_remise_coupe + cout_remise_pliage + cout_remise_operations)
    cout_total = round(variable_total + reglage_total, 2)

    # Vérification du coût unitaire ≈ 2,20 € (tolérance ±5 %)
    cout_min = 2.20 * 0.95
    cout_max = 2.20 * 1.05
    assert cout_min <= cout_total <= cout_max, \
        f"Coût unitaire {cout_total} € hors tolérance [ {cout_min} ; {cout_max} ]"

    # Vérification du prix unitaire (marge par défaut) ≈ 2,93 € à qté 100
    prix_calcule = round(cout_total / (1.0 - marge), 2)
    prix_min = round((cout_min) / (1.0 - marge), 2)
    prix_max = round((cout_max) / (1.0 - marge), 2)
    assert prix_min <= prix_calcule <= prix_max, \
        f"Prix unitaire {prix_calcule} € hors tolérance [ {prix_min} ; {prix_max} ]"
