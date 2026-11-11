"""Module de seed : valeurs simulées des référentiels + fonction de chargement idempotente.

Règle d'or : source de vérité = tables.py (SQLAlchemy). seed.py remplit uniquement
la base ; aucune valeur en dur ne doit apparaître ailleurs côté calcul.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from generateur_devis.data.tables import (
    BorneControle,
    Client,
    Composant,
    EpaisseurDispo,
    HistoriqueDevis,
    Matiere,
    Operation,
    Parametre,
    Poste,
    TempsPliage,
    Traitement,
    VitesseCoupe,
)

# ---------------------------------------------------------------------------
# 1. Données simulées — matières
# ---------------------------------------------------------------------------

_MATIERES = [
    Matiere(id="S235JR", famille="acier", nuance="S235JR", norme="EN 10025-2", densite_kg_dm3=7.85, prix_eur_kg=1.10, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
    Matiere(id="DC01", famille="acier", nuance="DC01", norme="EN 10130", densite_kg_dm3=7.85, prix_eur_kg=1.15, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
    Matiere(id="S355MC", famille="acier", nuance="S355MC", norme="EN 10149-2", densite_kg_dm3=7.85, prix_eur_kg=1.30, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
    Matiere(id="304L", famille="inox", nuance="X2CrNi18-9 (1.4307)", norme="EN 10088-2", densite_kg_dm3=7.90, prix_eur_kg=4.00, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
    Matiere(id="316L", famille="inox", nuance="X2CrNiMo17-12-2 (1.4404)", norme="EN 10088-2", densite_kg_dm3=8.00, prix_eur_kg=5.50, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
    Matiere(id="5754", famille="aluminium", nuance="EN AW-5754 H111", norme="EN 485", densite_kg_dm3=2.66, prix_eur_kg=4.80, date_maj=date(2026, 11, 1), fournisseur="Fournisseur fictif"),
]

# ---------------------------------------------------------------------------
# 2. Données simulées — épaisseurs disponibles
# ---------------------------------------------------------------------------

_EPAISSEURS_DISPO: dict[str, list[EpaisseurDispo]] = {
    "S235JR": [
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=1.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=1.5, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=2.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=3.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=4.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=5.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=6.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=8.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="S235JR", epaisseur_mm=10.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
    ],
    "DC01": [
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=0.8, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=1.0, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=1.5, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=2.0, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=2.5, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="DC01", epaisseur_mm=3.0, format_mm="2500 × 1250", surcout_pct=0.0, en_stock=True),
    ],
    "304L": [
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=1.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=1.5, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=2.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=3.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=4.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="304L", epaisseur_mm=5.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
    ],
    "316L": [
        EpaisseurDispo(matiere_id="316L", epaisseur_mm=1.0, format_mm="2000 × 1000", surcout_pct=10.0, en_stock=False),
        EpaisseurDispo(matiere_id="316L", epaisseur_mm=1.5, format_mm="2000 × 1000", surcout_pct=10.0, en_stock=False),
        EpaisseurDispo(matiere_id="316L", epaisseur_mm=2.0, format_mm="2000 × 1000", surcout_pct=10.0, en_stock=False),
        EpaisseurDispo(matiere_id="316L", epaisseur_mm=3.0, format_mm="2000 × 1000", surcout_pct=10.0, en_stock=False),
    ],
    "5754": [
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=1.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=1.5, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=2.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=3.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=4.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
        EpaisseurDispo(matiere_id="5754", epaisseur_mm=5.0, format_mm="3000 × 1500", surcout_pct=0.0, en_stock=True),
    ],
}

# ---------------------------------------------------------------------------
# 3. Données simulées — postes machine
# ---------------------------------------------------------------------------

_POSTES = [
    Poste(id="LASER_3KW", nom="Laser fibre 3 kW", type="decoupe", taux_horaire_eur_h=120.0, temps_reglage_min=15.0),
    Poste(id="PLIEUSE_CN", nom="Presse plieuse CN 100 t", type="pliage", taux_horaire_eur_h=70.0, temps_reglage_min=20.0),
    Poste(id="SOUDURE_MIG", nom="Poste soudure MIG", type="soudure", taux_horaire_eur_h=60.0, temps_reglage_min=15.0),
    Poste(id="SERTISSEUSE", nom="Presse à sertir", type="sertissage", taux_horaire_eur_h=50.0, temps_reglage_min=10.0),
    Poste(id="MANUEL", nom="Poste manuel (ébavurage, taraudage, controle)", type="manuel", taux_horaire_eur_h=50.0, temps_reglage_min=0.0),
]

# ---------------------------------------------------------------------------
# 4. Données simulées — vitesses de coupe
# ---------------------------------------------------------------------------

_VITESSES_COUPE: list[VitesseCoupe] = [
    # acier
    VitesseCoupe(poste_id="LASER_3KW", famille="acier", epaisseur_mm=1.0, vitesse_m_min=7.0, temps_amorcage_s=0.7, gaz="O2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="acier", epaisseur_mm=2.0, vitesse_m_min=5.0, temps_amorcage_s=1.0, gaz="O2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="acier", epaisseur_mm=3.0, vitesse_m_min=3.5, temps_amorcage_s=1.2, gaz="O2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="acier", epaisseur_mm=5.0, vitesse_m_min=2.2, temps_amorcage_s=1.5, gaz="O2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="acier", epaisseur_mm=10.0, vitesse_m_min=1.0, temps_amorcage_s=3.0, gaz="O2"),
    # inox
    VitesseCoupe(poste_id="LASER_3KW", famille="inox", epaisseur_mm=1.0, vitesse_m_min=6.0, temps_amorcage_s=0.6, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="inox", epaisseur_mm=2.0, vitesse_m_min=3.5, temps_amorcage_s=1.0, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="inox", epaisseur_mm=3.0, vitesse_m_min=2.2, temps_amorcage_s=1.3, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="inox", epaisseur_mm=5.0, vitesse_m_min=1.2, temps_amorcage_s=2.0, gaz="N2"),
    # aluminium
    VitesseCoupe(poste_id="LASER_3KW", famille="aluminium", epaisseur_mm=1.0, vitesse_m_min=7.0, temps_amorcage_s=0.6, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="aluminium", epaisseur_mm=2.0, vitesse_m_min=4.0, temps_amorcage_s=1.0, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="aluminium", epaisseur_mm=3.0, vitesse_m_min=2.5, temps_amorcage_s=1.3, gaz="N2"),
    VitesseCoupe(poste_id="LASER_3KW", famille="aluminium", epaisseur_mm=5.0, vitesse_m_min=1.2, temps_amorcage_s=2.0, gaz="N2"),
]

# ---------------------------------------------------------------------------
# 5. Données simulées — temps de pliage
# ---------------------------------------------------------------------------

_TEMPS_PLIAGE: list[TempsPliage] = [
    # petite
    TempsPliage(categorie="petite", dim_max_mm=300, epaisseur_max_mm=3.0, temps_par_pli_s=8.0, temps_retournement_s=3.0, nb_operateurs=1),
    TempsPliage(categorie="petite", dim_max_mm=300, epaisseur_max_mm=10.0, temps_par_pli_s=12.0, temps_retournement_s=4.0, nb_operateurs=1),
    # moyenne
    TempsPliage(categorie="moyenne", dim_max_mm=1000, epaisseur_max_mm=3.0, temps_par_pli_s=15.0, temps_retournement_s=6.0, nb_operateurs=1),
    TempsPliage(categorie="moyenne", dim_max_mm=1000, epaisseur_max_mm=10.0, temps_par_pli_s=20.0, temps_retournement_s=8.0, nb_operateurs=1),
    # grande
    TempsPliage(categorie="grande", dim_max_mm=3000, epaisseur_max_mm=3.0, temps_par_pli_s=30.0, temps_retournement_s=15.0, nb_operateurs=2),
    TempsPliage(categorie="grande", dim_max_mm=3000, epaisseur_max_mm=10.0, temps_par_pli_s=45.0, temps_retournement_s=20.0, nb_operateurs=2),
]

# ---------------------------------------------------------------------------
# 6. Données simulées — opérations standards
# ---------------------------------------------------------------------------

_OPERATIONS: list[Operation] = [
    Operation(id="SERTISSAGE", nom="Pose d'un écrou / goujon à sertir", poste_id="SERTISSEUSE", temps_s=12.0, unite="par insert"),
    Operation(id="TARAUDAGE", nom="Taraudage d'un trou", poste_id="MANUEL", temps_s=20.0, unite="par trou"),
    Operation(id="FRAISURAGE", nom="Fraisurage d'un trou", poste_id="MANUEL", temps_s=15.0, unite="par trou"),
    Operation(id="EBAVURAGE_P", nom="Ébavurage petite pièce", poste_id="MANUEL", temps_s=10.0, unite="par pièce"),
    Operation(id="EBAVURAGE_G", nom="Ébavurage grande pièce", poste_id="MANUEL", temps_s=40.0, unite="par pièce"),
    Operation(id="SOUDURE_MIG", nom="Cordon de soudure MIG", poste_id="SOUDURE_MIG", temps_s=200.0, unite="par mètre"),
    Operation(id="POINT_SOUDURE", nom="Point de soudure", poste_id="SOUDURE_MIG", temps_s=5.0, unite="par point"),
    Operation(id="PREPA_SOUDURE", nom="Pointage, préparation, meulage", poste_id="SOUDURE_MIG", temps_s=0.0, unite="du temps d'arc"),
    Operation(id="MARQUAGE", nom="Marquage de la référence", poste_id="MANUEL", temps_s=5.0, unite="par pièce"),
    Operation(id="CONTROLE", nom="Contrôle dimensionnel", poste_id="MANUEL", temps_s=30.0, unite="par pièce contrôlée"),
]

# ---------------------------------------------------------------------------
# 7. Données simulées — composants achetés
# ---------------------------------------------------------------------------

_COMPOSANTS: list[Composant] = [
    Composant(reference="ES-M4-A", designation="Écrou à sertir M4", type="ecrou_sertir", filetage="M4", matiere="acier zingué", prix_unitaire_eur=0.15, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="ES-M5-A", designation="Écrou à sertir M5", type="ecrou_sertir", filetage="M5", matiere="acier zingué", prix_unitaire_eur=0.18, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="ES-M6-A", designation="Écrou à sertir M6", type="ecrou_sertir", filetage="M6", matiere="acier zingué", prix_unitaire_eur=0.20, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="ES-M6-B", designation="Écrou à sertir M6 (lot 1000)", type="ecrou_sertir", filetage="M6", matiere="acier zingué", prix_unitaire_eur=0.15, qte_min=1000, operation_id="SERTISSAGE"),
    Composant(reference="ES-M8-A", designation="Écrou à sertir M8", type="ecrou_sertir", filetage="M8", matiere="acier zingué", prix_unitaire_eur=0.28, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="ES-M6-X", designation="Écrou à sertir M6 inox", type="ecrou_sertir", filetage="M6", matiere="inox A2", prix_unitaire_eur=0.45, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="GS-M6-A", designation="Goujon à sertir M6 × 16", type="goujon_sertir", filetage="M6", matiere="acier zingué", prix_unitaire_eur=0.25, qte_min=1, operation_id="SERTISSAGE"),
    Composant(reference="ENT-M4-10", designation="Entretoise à sertir M4 × 10", type="entretoise", filetage="M4", matiere="acier zingué", prix_unitaire_eur=0.30, qte_min=1, operation_id="SERTISSAGE"),
]

# ---------------------------------------------------------------------------
# 8. Données simulées — traitements de surface
# ---------------------------------------------------------------------------

_TRAITEMENTS: list[Traitement] = [
    Traitement(id="PEINTURE_POUDRE", nom="Thermolaquage 1 couche", prix=35.0, unite="m2", minimum_lot_eur=80.0, delai_jours=5, matieres_compatibles="acier, aluminium"),
    Traitement(id="CATAPHORESE", nom="Cataphorèse", prix=20.0, unite="m2", minimum_lot_eur=100.0, delai_jours=7, matieres_compatibles="acier"),
    Traitement(id="ZINGAGE", nom="Zingage électrolytique", prix=15.0, unite="m2", minimum_lot_eur=60.0, delai_jours=5, matieres_compatibles="acier"),
    Traitement(id="GALVA_CHAUD", nom="Galvanisation à chaud", prix=0.80, unite="kg", minimum_lot_eur=100.0, delai_jours=10, matieres_compatibles="acier"),
    Traitement(id="PASSIVATION", nom="Passivation", prix=25.0, unite="m2", minimum_lot_eur=80.0, delai_jours=5, matieres_compatibles="inox"),
    Traitement(id="ANODISATION", nom="Anodisation naturelle", prix=30.0, unite="m2", minimum_lot_eur=90.0, delai_jours=7, matieres_compatibles="aluminium"),
    Traitement(id="MASQUAGE", nom="Épargne / masquage d'une zone", prix=0.10, unite="zone", minimum_lot_eur=0.0, delai_jours=0, matieres_compatibles="toutes"),
]

# ---------------------------------------------------------------------------
# 9. Données simulées — paramètres globaux
# ---------------------------------------------------------------------------

_PARAMETRES_DEFAUT: dict[str, Any] = {
    "marge_defaut": "0.25",
    "rendement_calepinage": "0.80",
    "facteur_k": "0.40",
    "frais_structure_pct": "0",
    "minimum_commande_eur": "0",
    "paliers_quantite": "1, 10, 100, 1000",
    "devise": "EUR",
    "validite_devis_jours": "30",
    # Seuils des règles de faisabilité (multiples de l'épaisseur, §3b architecture)
    "regle_diam_trou_min_e": "1.0",
    "regle_aile_min_e": "4.0",
    "regle_rayon_min_e": "1.0",
    # Postes utilisés par le moteur de chiffrage (identifiants de la table postes)
    "poste_decoupe": "LASER_3KW",
    "poste_pliage": "PLIEUSE_CN",
    # Opérations secondaires appliquées par le moteur de chiffrage (table operations)
    "operation_ebavurage": "EBAVURAGE_P",
    "operation_taraudage": "TARAUDAGE",
    # Âge max d'un prix matière avant alerte (contrôles de cohérence du chiffrage)
    "prix_matiere_max_age_jours": "180",
}

# ---------------------------------------------------------------------------
# 10. Données simulées — clients
# ---------------------------------------------------------------------------

_CLIENTS: list[Client] = [
    Client(id="CLI001", nom="Client Alpha", secteur="Poids lourds", marge_specifique=0.18, ia_externe_autorisee=True, reutilisation_autorisee=True, duree_conservation_plans_jours=365, suppression_si_refus=False),
    Client(id="CLI002", nom="Client Bêta", secteur="Machines agricoles", marge_specifique=0.25, ia_externe_autorisee=True, reutilisation_autorisee=False, duree_conservation_plans_jours=90, suppression_si_refus=True),
    Client(id="CLI003", nom="Client Gamma", secteur="Ferroviaire", marge_specifique=0.30, ia_externe_autorisee=False, reutilisation_autorisee=False, duree_conservation_plans_jours=90, suppression_si_refus=True),
    Client(id="CLI004", nom="Client Delta", secteur="Agencement", marge_specifique=None, ia_externe_autorisee=True, reutilisation_autorisee=True, duree_conservation_plans_jours=90, suppression_si_refus=True),
]

# ---------------------------------------------------------------------------
# 11. Fonctions utilitaires
# ---------------------------------------------------------------------------

def _generer_coût_unitaire(matiere_id: str, epaisseur_mm: float, quantité: int) -> float:
    """Calcul simple du coût matière unitaire (hors main-d'œuvre, traitements, composants).

    Utilise la densité de la matière, l'épaisseur et une zone de flan standard
    (4500 mm², format piece_support : 75 × 60 mm, soit la référence §8.3)
    avec rendement de calepinage 0,80, conformément à docs/logique_metier.md §1 et §8.
    """
    matiere = next(m for m in _MATIERES if m.id == matiere_id)
    zone_mm2 = 4500.0  # format standard piece_support : 75 × 60 mm (§8.3), surface englobante du flan
    masse_kg = zone_mm2 * epaisseur_mm * matiere.densite_kg_dm3 / 1_000_000
    coût_matière = masse_kg / 0.80 * matiere.prix_eur_kg
    return round(coût_matière, 2)

def _prix_avec_marge(cout: float, marge: float) -> float:
    """Prix = coût ÷ (1 − marge)"""
    if marge <= 0 or marge >= 1:
        return round(cout, 2)
    return round(cout / (1.0 - marge), 2)

def _ajouter_bruit(valeur: float, bruit_pct: float) -> float:
    """Bruit aléatoire ± bruit_pct %."""
    if bruit_pct <= 0:
        return round(valeur, 2)
    écart = random.uniform(-bruit_pct, bruit_pct) / 100.0 * valeur
    return round(valeur + écart, 2)

# ---------------------------------------------------------------------------
# 12. Fonction de seed idempotente
# ---------------------------------------------------------------------------

def seed(session: Session) -> None:
    """Charger toutes les valeurs simulées en base. Idempotent : merge (upsert).

    Strategy : SQLAlchemy merge on conflict. Toutes les tables sont remplies à partir
    des définitions ci-dessus ; aucune valeur en dur n'est codée dans le moteur.
    """

    # --- matières ---
    for m in _MATIERES:
        session.merge(m)
    session.commit()

    # --- épaisseurs disponibles ---
    for _matiere_id, lignes in _EPAISSEURS_DISPO.items():
        for lign in lignes:
            session.merge(lign)
    session.commit()

    # --- postes ---
    for p in _POSTES:
        session.merge(p)
    session.commit()

    # --- vitesses de coupe ---
    for v in _VITESSES_COUPE:
        session.merge(v)
    session.commit()

    # --- temps de pliage ---
    for t in _TEMPS_PLIAGE:
        session.merge(t)
    session.commit()

    # --- opérations ---
    for op in _OPERATIONS:
        session.merge(op)
    session.commit()

    # --- composants ---
    for c in _COMPOSANTS:
        session.merge(c)
    session.commit()

    # --- traitements ---
    for tr in _TRAITEMENTS:
        session.merge(tr)
    session.commit()

    # --- paramètres globaux ---
    for cle, valeur in _PARAMETRES_DEFAUT.items():
        param = session.get(Parametre, cle)
        if param is None:
            param = Parametre(cle=cle, valeur=valeur, unite="taux" if cle != "devise" else None, description=f"Paramètre global {cle}")
        else:
            param.valeur = valeur
        session.add(param)
    session.commit()

    # --- clients ---
    for c in _CLIENTS:
        session.merge(c)
    session.commit()

    # --- historique des devis (~30 lignes avec bruit ±10-15%) ---
    random.seed(42)  # reproductibilité
    nb_historique = 30
    for i in range(nb_historique):
        matiere_id = random.choice(["S235JR", "DC01", "304L", "316L", "5754"])
        epaisseur_ligne = random.choice(_EPAISSEURS_DISPO[matiere_id])
        epaisseur_mm = epaisseur_ligne.epaisseur_mm
        client = random.choice(_CLIENTS)
        jour_aleatoire = random.randint(1, 30)
        date_devis = date(2026, 1, 1) + timedelta(days=jour_aleatoire)
        quantite = random.randint(1, 500)
        base_coût = _generer_coût_unitaire(matiere_id, epaisseur_mm, quantite)
        marge_client = client.marge_specifique if client.marge_specifique is not None else float(_PARAMETRES_DEFAUT["marge_defaut"])
        prix_de_base = _prix_avec_marge(base_coût, marge_client)
        prix_bruité = _ajouter_bruit(prix_de_base, random.uniform(10, 15))
        cout_bruité = _ajouter_bruit(base_coût, random.uniform(10, 15))
        nb_plis = random.randint(0, 4)
        nb_trous = random.randint(0, 6)
        nb_composants = random.randint(0, 8)
        traitements_possibles = [t.id for t in _TRAITEMENTS] + [None]
        traitement_id = random.choice(traitements_possibles)
        longueur_coupe = round(random.uniform(10, 200), 1)
        flan_l = round(random.uniform(50, 600), 1)
        flan_w = round(random.uniform(30, 300), 1)
        masse = round(random.uniform(0.5, 50.0), 2)
        statut = random.choice(["accepte", "refuse", "en_attente"])
        references = ["Patte de fixation", "Capot", "Support inox", "Bride", "Renfort", "Cache", "Socle", "Arêtier"]
        reference_piece = random.choice(references)
        designation = reference_piece

        hd = HistoriqueDevis(
            id=f"D-2026-{i+1:04d}",
            date=date_devis,
            client_id=client.id,
            reference_piece=reference_piece,
            designation=designation,
            matiere_id=matiere_id,
            epaisseur_mm=round(epaisseur_mm, 2),
            flan_l_mm=flan_l,
            flan_w_mm=flan_w,
            masse_kg=masse,
            longueur_coupe_mm=longueur_coupe,
            nb_trous=nb_trous,
            nb_plis=nb_plis,
            nb_composants=nb_composants,
            traitement_id=traitement_id,
            quantite=quantite,
            cout_unitaire_eur=cout_bruité,
            prix_unitaire_eur=prix_bruité,
            statut=statut,
        )
        session.merge(hd)
    session.commit()

    # --- bornes de contrôle ---
    bornes = [
        BorneControle(champ="epaisseur_mm", min=0.5, max=20.0, niveau="bloquant", message="Épaisseur hors capacité atelier"),
        BorneControle(champ="flan_dim_max_mm", min=10, max=3000, niveau="bloquant", message="Pièce plus grande que le format de tôle"),
        BorneControle(champ="ratio_surface_dev_surface_vue", min=0.7, max=3.0, niveau="alerte", message="Surface développée incohérente avec les vues"),
        BorneControle(champ="ratio_longueur_coupe_périmètre_flan", min=0.7, max=10, niveau="alerte", message="Longueur de découpe incohérente"),
        BorneControle(champ="ecart_masse_calculee_pct", min=-15, max=15, niveau="alerte", message="Masse incohérente avec surface × épaisseur"),
        BorneControle(champ="prix_eur_kg_masse_gt_1kg", min=2, max=50, niveau="alerte", message="Prix au kg inhabituel"),
        BorneControle(champ="prix_eur_kg_masse_le_1kg", min=2, max=150, niveau="alerte", message="Prix au kg inhabituel pour une petite pièce"),
        BorneControle(champ="part_matiere_pct_qte_gte_100", min=3, max=70, niveau="alerte", message="Répartition des coûts inhabituelle"),
        BorneControle(champ="ecart_historique_pct", min=-30, max=30, niveau="alerte", message="Écart important avec des pièces similaires"),
        BorneControle(champ="marge", min=0.05, max=0.50, niveau="alerte", message="Marge hors politique commerciale"),
    ]
    for b in bornes:
        session.merge(b)
    session.commit()
