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
    Matiere(
        id="S235JR",
        famille="acier",
        nuance="S235JR",
        norme="EN 10025-2",
        densite_kg_dm3=7.85,
        prix_eur_kg=1.10,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
    Matiere(
        id="DC01",
        famille="acier",
        nuance="DC01",
        norme="EN 10130",
        densite_kg_dm3=7.85,
        prix_eur_kg=1.15,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
    Matiere(
        id="S355MC",
        famille="acier",
        nuance="S355MC",
        norme="EN 10149-2",
        densite_kg_dm3=7.85,
        prix_eur_kg=1.30,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
    Matiere(
        id="304L",
        famille="inox",
        nuance="X2CrNi18-9 (1.4307)",
        norme="EN 10088-2",
        densite_kg_dm3=7.90,
        prix_eur_kg=4.00,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
    Matiere(
        id="316L",
        famille="inox",
        nuance="X2CrNiMo17-12-2 (1.4404)",
        norme="EN 10088-2",
        densite_kg_dm3=8.00,
        prix_eur_kg=5.50,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
    Matiere(
        id="5754",
        famille="aluminium",
        nuance="EN AW-5754 H111",
        norme="EN 485",
        densite_kg_dm3=2.66,
        prix_eur_kg=4.80,
        date_maj=date(2026, 11, 1),
        fournisseur="Fournisseur fictif",
    ),
]

# ---------------------------------------------------------------------------
# 2. Données simulées — épaisseurs disponibles
# ---------------------------------------------------------------------------

_EPAISSEURS_DISPO: dict[str, list[EpaisseurDispo]] = {
    "S235JR": [
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=1.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=1.5,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=2.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=3.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=4.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=5.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=6.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=8.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="S235JR",
            epaisseur_mm=10.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
    ],
    "DC01": [
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=0.8,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=1.0,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=1.5,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=2.0,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=2.5,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="DC01",
            epaisseur_mm=3.0,
            format_mm="2500 × 1250",
            surcout_pct=0.0,
            en_stock=True,
        ),
    ],
    "304L": [
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=1.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=1.5,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=2.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=3.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=4.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="304L",
            epaisseur_mm=5.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
    ],
    "316L": [
        EpaisseurDispo(
            matiere_id="316L",
            epaisseur_mm=1.0,
            format_mm="2000 × 1000",
            surcout_pct=10.0,
            en_stock=False,
        ),
        EpaisseurDispo(
            matiere_id="316L",
            epaisseur_mm=1.5,
            format_mm="2000 × 1000",
            surcout_pct=10.0,
            en_stock=False,
        ),
        EpaisseurDispo(
            matiere_id="316L",
            epaisseur_mm=2.0,
            format_mm="2000 × 1000",
            surcout_pct=10.0,
            en_stock=False,
        ),
        EpaisseurDispo(
            matiere_id="316L",
            epaisseur_mm=3.0,
            format_mm="2000 × 1000",
            surcout_pct=10.0,
            en_stock=False,
        ),
    ],
    "5754": [
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=1.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=1.5,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=2.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=3.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=4.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
        EpaisseurDispo(
            matiere_id="5754",
            epaisseur_mm=5.0,
            format_mm="3000 × 1500",
            surcout_pct=0.0,
            en_stock=True,
        ),
    ],
}

# ---------------------------------------------------------------------------
# 3. Données simulées — postes machine
# ---------------------------------------------------------------------------

_POSTES = [
    Poste(
        id="LASER_3KW",
        nom="Laser fibre 3 kW",
        type="decoupe",
        taux_horaire_eur_h=120.0,
        temps_reglage_min=15.0,
    ),
    Poste(
        id="PLIEUSE_CN",
        nom="Presse plieuse CN 100 t",
        type="pliage",
        taux_horaire_eur_h=70.0,
        temps_reglage_min=20.0,
    ),
    Poste(
        id="SOUDURE_MIG",
        nom="Poste soudure MIG",
        type="soudure",
        taux_horaire_eur_h=60.0,
        temps_reglage_min=15.0,
    ),
    Poste(
        id="SERTISSEUSE",
        nom="Presse à sertir",
        type="sertissage",
        taux_horaire_eur_h=50.0,
        temps_reglage_min=10.0,
    ),
    Poste(
        id="MANUEL",
        nom="Poste manuel (ébavurage, taraudage, controle)",
        type="manuel",
        taux_horaire_eur_h=50.0,
        temps_reglage_min=0.0,
    ),
]

# ---------------------------------------------------------------------------
# 4. Données simulées — vitesses de coupe
# ---------------------------------------------------------------------------

_VITESSES_COUPE: list[VitesseCoupe] = [
    # acier
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=1.0,
        vitesse_m_min=7.0,
        temps_amorcage_s=0.7,
        gaz="O2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=1.5,
        vitesse_m_min=6.0,
        temps_amorcage_s=0.9,
        gaz="O2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=2.0,
        vitesse_m_min=5.0,
        temps_amorcage_s=1.0,
        gaz="O2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=3.0,
        vitesse_m_min=3.5,
        temps_amorcage_s=1.2,
        gaz="O2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=5.0,
        vitesse_m_min=2.2,
        temps_amorcage_s=1.5,
        gaz="O2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="acier",
        epaisseur_mm=10.0,
        vitesse_m_min=1.0,
        temps_amorcage_s=3.0,
        gaz="O2",
    ),
    # inox
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="inox",
        epaisseur_mm=1.0,
        vitesse_m_min=6.0,
        temps_amorcage_s=0.6,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="inox",
        epaisseur_mm=1.5,
        vitesse_m_min=4.8,
        temps_amorcage_s=0.8,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="inox",
        epaisseur_mm=2.0,
        vitesse_m_min=3.5,
        temps_amorcage_s=1.0,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="inox",
        epaisseur_mm=3.0,
        vitesse_m_min=2.2,
        temps_amorcage_s=1.3,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="inox",
        epaisseur_mm=5.0,
        vitesse_m_min=1.2,
        temps_amorcage_s=2.0,
        gaz="N2",
    ),
    # aluminium
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="aluminium",
        epaisseur_mm=1.0,
        vitesse_m_min=7.0,
        temps_amorcage_s=0.6,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="aluminium",
        epaisseur_mm=1.5,
        vitesse_m_min=5.5,
        temps_amorcage_s=0.8,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="aluminium",
        epaisseur_mm=2.0,
        vitesse_m_min=4.0,
        temps_amorcage_s=1.0,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="aluminium",
        epaisseur_mm=3.0,
        vitesse_m_min=2.5,
        temps_amorcage_s=1.3,
        gaz="N2",
    ),
    VitesseCoupe(
        poste_id="LASER_3KW",
        famille="aluminium",
        epaisseur_mm=5.0,
        vitesse_m_min=1.2,
        temps_amorcage_s=2.0,
        gaz="N2",
    ),
]

# ---------------------------------------------------------------------------
# 5. Données simulées — temps de pliage
# ---------------------------------------------------------------------------

_TEMPS_PLIAGE: list[TempsPliage] = [
    # petite
    TempsPliage(
        categorie="petite",
        dim_max_mm=300,
        epaisseur_max_mm=3.0,
        temps_par_pli_s=8.0,
        temps_retournement_s=3.0,
        nb_operateurs=1,
    ),
    TempsPliage(
        categorie="petite",
        dim_max_mm=300,
        epaisseur_max_mm=10.0,
        temps_par_pli_s=12.0,
        temps_retournement_s=4.0,
        nb_operateurs=1,
    ),
    # moyenne
    TempsPliage(
        categorie="moyenne",
        dim_max_mm=1000,
        epaisseur_max_mm=3.0,
        temps_par_pli_s=15.0,
        temps_retournement_s=6.0,
        nb_operateurs=1,
    ),
    TempsPliage(
        categorie="moyenne",
        dim_max_mm=1000,
        epaisseur_max_mm=10.0,
        temps_par_pli_s=20.0,
        temps_retournement_s=8.0,
        nb_operateurs=1,
    ),
    # grande
    TempsPliage(
        categorie="grande",
        dim_max_mm=3000,
        epaisseur_max_mm=3.0,
        temps_par_pli_s=30.0,
        temps_retournement_s=15.0,
        nb_operateurs=2,
    ),
    TempsPliage(
        categorie="grande",
        dim_max_mm=3000,
        epaisseur_max_mm=10.0,
        temps_par_pli_s=45.0,
        temps_retournement_s=20.0,
        nb_operateurs=2,
    ),
]

# ---------------------------------------------------------------------------
# 6. Données simulées — opérations standards
# ---------------------------------------------------------------------------

_OPERATIONS: list[Operation] = [
    Operation(
        id="SERTISSAGE",
        nom="Pose d'un écrou / goujon à sertir",
        poste_id="SERTISSEUSE",
        temps_s=12.0,
        unite="par insert",
    ),
    Operation(
        id="TARAUDAGE", nom="Taraudage d'un trou", poste_id="MANUEL", temps_s=20.0, unite="par trou"
    ),
    Operation(
        id="FRAISURAGE",
        nom="Fraisurage d'un trou",
        poste_id="MANUEL",
        temps_s=15.0,
        unite="par trou",
    ),
    Operation(
        id="EBAVURAGE_P",
        nom="Ébavurage petite pièce",
        poste_id="MANUEL",
        temps_s=10.0,
        unite="par pièce",
    ),
    Operation(
        id="EBAVURAGE_G",
        nom="Ébavurage grande pièce",
        poste_id="MANUEL",
        temps_s=40.0,
        unite="par pièce",
    ),
    Operation(
        id="SOUDURE_MIG",
        nom="Cordon de soudure MIG",
        poste_id="SOUDURE_MIG",
        temps_s=200.0,
        unite="par mètre",
    ),
    Operation(
        id="POINT_SOUDURE",
        nom="Point de soudure",
        poste_id="SOUDURE_MIG",
        temps_s=5.0,
        unite="par point",
    ),
    Operation(
        id="PREPA_SOUDURE",
        nom="Pointage, préparation, meulage",
        poste_id="SOUDURE_MIG",
        temps_s=0.0,
        unite="du temps d'arc",
    ),
    Operation(
        id="MARQUAGE",
        nom="Marquage de la référence",
        poste_id="MANUEL",
        temps_s=5.0,
        unite="par pièce",
    ),
    Operation(
        id="CONTROLE",
        nom="Contrôle dimensionnel",
        poste_id="MANUEL",
        temps_s=30.0,
        unite="par pièce contrôlée",
    ),
]

# ---------------------------------------------------------------------------
# 7. Données simulées — composants achetés
# ---------------------------------------------------------------------------

_COMPOSANTS: list[Composant] = [
    Composant(
        reference="ES-M4-A",
        designation="Écrou à sertir M4",
        type="ecrou_sertir",
        filetage="M4",
        matiere="acier zingué",
        prix_unitaire_eur=0.15,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ES-M5-A",
        designation="Écrou à sertir M5",
        type="ecrou_sertir",
        filetage="M5",
        matiere="acier zingué",
        prix_unitaire_eur=0.18,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ES-M6-A",
        designation="Écrou à sertir M6",
        type="ecrou_sertir",
        filetage="M6",
        matiere="acier zingué",
        prix_unitaire_eur=0.20,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ES-M6-B",
        designation="Écrou à sertir M6 (lot 1000)",
        type="ecrou_sertir",
        filetage="M6",
        matiere="acier zingué",
        prix_unitaire_eur=0.15,
        qte_min=1000,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ES-M8-A",
        designation="Écrou à sertir M8",
        type="ecrou_sertir",
        filetage="M8",
        matiere="acier zingué",
        prix_unitaire_eur=0.28,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ES-M6-X",
        designation="Écrou à sertir M6 inox",
        type="ecrou_sertir",
        filetage="M6",
        matiere="inox A2",
        prix_unitaire_eur=0.45,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="GS-M6-A",
        designation="Goujon à sertir M6 × 16",
        type="goujon_sertir",
        filetage="M6",
        matiere="acier zingué",
        prix_unitaire_eur=0.25,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
    Composant(
        reference="ENT-M4-10",
        designation="Entretoise à sertir M4 × 10",
        type="entretoise",
        filetage="M4",
        matiere="acier zingué",
        prix_unitaire_eur=0.30,
        qte_min=1,
        operation_id="SERTISSAGE",
    ),
]

# ---------------------------------------------------------------------------
# 8. Données simulées — traitements de surface
# ---------------------------------------------------------------------------

_TRAITEMENTS: list[Traitement] = [
    Traitement(
        id="PEINTURE_POUDRE",
        nom="Thermolaquage 1 couche",
        prix=35.0,
        unite="m2",
        minimum_lot_eur=80.0,
        delai_jours=5,
        matieres_compatibles="acier, aluminium",
    ),
    Traitement(
        id="CATAPHORESE",
        nom="Cataphorèse",
        prix=20.0,
        unite="m2",
        minimum_lot_eur=100.0,
        delai_jours=7,
        matieres_compatibles="acier",
    ),
    Traitement(
        id="ZINGAGE",
        nom="Zingage électrolytique",
        prix=15.0,
        unite="m2",
        minimum_lot_eur=60.0,
        delai_jours=5,
        matieres_compatibles="acier",
    ),
    Traitement(
        id="GALVA_CHAUD",
        nom="Galvanisation à chaud",
        prix=0.80,
        unite="kg",
        minimum_lot_eur=100.0,
        delai_jours=10,
        matieres_compatibles="acier",
    ),
    Traitement(
        id="PASSIVATION",
        nom="Passivation",
        prix=25.0,
        unite="m2",
        minimum_lot_eur=80.0,
        delai_jours=5,
        matieres_compatibles="inox",
    ),
    Traitement(
        id="ANODISATION",
        nom="Anodisation naturelle",
        prix=30.0,
        unite="m2",
        minimum_lot_eur=90.0,
        delai_jours=7,
        matieres_compatibles="aluminium",
    ),
    Traitement(
        id="MASQUAGE",
        nom="Épargne / masquage d'une zone",
        prix=0.10,
        unite="zone",
        minimum_lot_eur=0.0,
        delai_jours=0,
        matieres_compatibles="toutes",
    ),
]

# ---------------------------------------------------------------------------
# 9. Données simulées — paramètres globaux
# ---------------------------------------------------------------------------

_PARAMETRES_DEFAUT: dict[str, Any] = {
    "marge_defaut": "0.25",
    # Borne haute métier de toute marge (devis, marge_defaut, marges clients) :
    # au-delà, refus ⛔ (une faute de frappe 0,99 multiplie le prix par 100).
    "marge_max": "0.6",
    "seuil_confiance_champs": "0.7",
    "rendement_calepinage": "0.80",
    "facteur_k": "0.40",
    "frais_structure_pct": "0",
    "minimum_commande_eur": "0",
    "paliers_quantite": "1, 10, 100, 1000",
    "devise": "EUR",
    "validite_devis_jours": "30",
    "conditions_generales": "Prix HT, départ atelier.",
    # Modèle d'extraction unique, administrable (invisible côté devis) ;
    # surchargeable par la variable d'environnement MODELE_EXTRACTION.
    "modele_extraction": "claude-code:sonnet",
    # Rayon de pliage intérieur proposé par défaut sur l'écran de validation
    # quand le plan ne cote aucun rayon (ni par pli, ni en note générale) —
    # règle atelier usuelle R ≈ épaisseur ; valeur administrable par l'agent.
    "rayon_pliage_defaut_mm": "1.0",
    # Échantillon minimum de devis similaires pour que le contrôle
    # ecart_historique s'applique — une « moyenne » sur 1-2 devis ne veut
    # rien dire.
    "ecart_historique_min_echantillon": "3",
    # Seuils des règles de faisabilité (multiples de l'épaisseur, §3b architecture)
    "regle_diam_trou_min_e": "1.0",
    "regle_aile_min_e": "4.0",
    "regle_rayon_min_e": "1.0",
    # Rayon > k × e → alerte (outillage spécial ou roulage, à vérifier)
    "regle_rayon_max_e": "8.0",
    # Rayon > k × plus courte aile adjacente au pli → blocage (irréalisable)
    "regle_rayon_max_aile": "1.0",
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
    Client(
        id="CLI001",
        nom="Client Alpha",
        secteur="Poids lourds",
        marge_specifique=0.18,
        ia_externe_autorisee=True,
        reutilisation_autorisee=True,
        duree_conservation_plans_jours=365,
        suppression_si_refus=False,
    ),
    Client(
        id="CLI002",
        nom="Client Bêta",
        secteur="Machines agricoles",
        marge_specifique=0.25,
        ia_externe_autorisee=True,
        reutilisation_autorisee=False,
        duree_conservation_plans_jours=90,
        suppression_si_refus=True,
    ),
    Client(
        id="CLI003",
        nom="Client Gamma",
        secteur="Ferroviaire",
        marge_specifique=0.30,
        ia_externe_autorisee=False,
        reutilisation_autorisee=False,
        duree_conservation_plans_jours=90,
        suppression_si_refus=True,
    ),
    Client(
        id="CLI004",
        nom="Client Delta",
        secteur="Agencement",
        marge_specifique=None,
        ia_externe_autorisee=True,
        reutilisation_autorisee=True,
        duree_conservation_plans_jours=90,
        suppression_si_refus=True,
    ),
]

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
            param = Parametre(
                cle=cle,
                valeur=valeur,
                unite="taux" if cle != "devise" else None,
                description=f"Paramètre global {cle}",
            )
        else:
            param.valeur = valeur
        session.add(param)
    session.commit()

    # --- clients ---
    for c in _CLIENTS:
        session.merge(c)
    session.commit()

    # --- historique des devis (30 lignes simulées, chiffrées par le moteur) ---
    # Chaque ligne reconstruit une pièce plausible (ailes égales, plis 90°,
    # trous ronds Ø8, composants du référentiel) puis la chiffre avec le
    # moteur actuel : l'historique est cohérent avec les devis produits,
    # ce qui rend le contrôle ecart_historique significatif.
    from generateur_devis.calcul_prix import chiffrer
    from generateur_devis.geometrie import construire_flan
    from generateur_devis.schema.piece import (
        Aile,
        Champ,
        Contours,
        Encombrement,
        Matiere,
        PieceExtraite,
        Pli,
        ProfilPliage,
        Traitement,
        Trou,
        TypeTraitement,
    )

    types_traitement = {
        "PEINTURE_POUDRE": "thermolaquage",
        "CATAPHORESE": "cataphorese",
        "ZINGAGE": "zingage",
        "GALVA_CHAUD": "galvanisation",
        "PASSIVATION": "passivation",
        "ANODISATION": "anodisation",
        # MASQUAGE : opération locale (par zone), pas une finition de pièce —
        # exclu du tirage (pas de type correspondant dans le schéma pièce).
    }
    familles = {m.id: m.famille for m in _MATIERES}
    densites = {m.id: m.densite_kg_dm3 for m in _MATIERES}
    epaisseurs_chiffrables = {(v.famille, v.epaisseur_mm) for v in _VITESSES_COUPE}
    facteur_k = float(_PARAMETRES_DEFAUT["facteur_k"])
    random.seed(42)  # reproductibilité
    nb_historique = 30
    for i in range(nb_historique):
        matiere_id = random.choice(["S235JR", "DC01", "304L", "316L", "5754"])
        famille = familles[matiere_id]
        epaisseurs_ok = [
            e.epaisseur_mm
            for e in _EPAISSEURS_DISPO[matiere_id]
            if (famille, e.epaisseur_mm) in epaisseurs_chiffrables
        ]
        epaisseur_mm = random.choice(epaisseurs_ok)
        client = random.choice(_CLIENTS)
        jour_aleatoire = random.randint(1, 30)
        date_devis = date(2026, 1, 1) + timedelta(days=jour_aleatoire)
        quantite = random.randint(1, 500)
        nb_plis = random.randint(0, 4)
        nb_trous = random.randint(0, 6)
        nb_composants = random.randint(0, 3)
        famille = familles[matiere_id]
        traitements_compatibles = [
            t.id
            for t in _TRAITEMENTS
            if t.id in types_traitement
            and t.unite == "m2"  # les tarifs au kg sont hors périmètre du chiffrage
            and (famille in t.matieres_compatibles or "toutes" in t.matieres_compatibles)
        ]
        traitement_id = random.choice(traitements_compatibles + [None])
        statut = random.choice(["accepte", "refuse", "en_attente"])
        references = [
            "Patte de fixation",
            "Capot",
            "Support inox",
            "Bride",
            "Renfort",
            "Cache",
            "Socle",
            "Arêtier",
        ]
        reference_piece = random.choice(references)
        designation = reference_piece

        elements = []
        for j in range(nb_plis + 1):
            elements.append(Aile(longueur=round(random.uniform(20, 120), 1)))
            if j < nb_plis:
                elements.append(Pli(angle=90.0, sens="haut"))
        piece = PieceExtraite(
            matiere=Matiere(
                designation=Champ[str](valeur=matiere_id),
                epaisseur=Champ[float](valeur=float(epaisseur_mm)),
            ),
            encombrement=Encombrement(
                largeur=Champ[float](valeur=round(random.uniform(30, 300), 1))
            ),
            profil_pliage=ProfilPliage(
                cotation="exterieure",
                rayon_pliage_general=float(epaisseur_mm),
                elements=elements,
            ),
            contours=Contours(
                trous=[Trou(forme="rond", diametre=8.0, quantite=nb_trous)] if nb_trous else []
            ),
            traitement=Traitement(
                type=Champ[TypeTraitement](valeur=types_traitement[traitement_id])
            )
            if traitement_id
            else Traitement(),
        )
        composants = [
            (c.reference, random.randint(1, 4)) for c in random.sample(_COMPOSANTS, k=nb_composants)
        ]
        chiffrage = chiffrer(
            piece,
            matiere_id,
            session,
            quantites=[quantite],
            composants=composants or None,
            client_id=client.id,
        )
        palier = chiffrage.paliers[0]
        flan = construire_flan(piece, densites[matiere_id], facteur_k)

        hd = HistoriqueDevis(
            id=f"D-2026-{i + 1:04d}",
            date=date_devis,
            client_id=client.id,
            reference_piece=reference_piece,
            designation=designation,
            matiere_id=matiere_id,
            epaisseur_mm=round(epaisseur_mm, 2),
            flan_l_mm=round(flan.longueur_developpee_mm, 1),
            flan_w_mm=round(flan.largeur_mm, 1),
            masse_kg=round(flan.masse_nette_kg, 3),
            longueur_coupe_mm=round(flan.longueur_coupe_mm, 1),
            nb_trous=nb_trous,
            nb_plis=nb_plis,
            nb_composants=nb_composants,
            traitement_id=traitement_id,
            quantite=quantite,
            cout_unitaire_eur=palier.cout_unitaire_eur,
            prix_unitaire_eur=palier.prix_unitaire_eur,
            statut=statut,
        )
        session.merge(hd)
    session.commit()

    # --- bornes de contrôle ---
    bornes = [
        BorneControle(
            champ="epaisseur_mm",
            min=0.5,
            max=20.0,
            niveau="bloquant",
            message="Épaisseur hors capacité atelier",
        ),
        BorneControle(
            champ="flan_dim_max_mm",
            min=10,
            max=3000,
            niveau="bloquant",
            message="Pièce plus grande que le format de tôle",
        ),
        BorneControle(
            champ="ratio_surface_dev_surface_vue",
            min=0.7,
            max=3.0,
            niveau="alerte",
            message="Surface développée incohérente avec les vues",
        ),
        BorneControle(
            champ="ratio_longueur_coupe_périmètre_flan",
            min=0.7,
            max=10,
            niveau="alerte",
            message="Longueur de découpe incohérente",
        ),
        BorneControle(
            champ="ecart_masse_calculee_pct",
            min=-15,
            max=15,
            niveau="alerte",
            message="Masse incohérente avec surface × épaisseur",
        ),
        BorneControle(
            champ="prix_eur_kg_masse_gt_1kg",
            min=2,
            max=50,
            niveau="alerte",
            message="Prix au kg inhabituel",
        ),
        BorneControle(
            champ="prix_eur_kg_masse_le_1kg",
            min=2,
            max=150,
            niveau="alerte",
            message="Prix au kg inhabituel pour une petite pièce",
        ),
        BorneControle(
            champ="part_matiere_pct_qte_gte_100",
            min=3,
            max=70,
            niveau="alerte",
            message="Répartition des coûts inhabituelle",
        ),
        BorneControle(
            champ="ecart_historique_pct",
            min=-30,
            max=30,
            niveau="alerte",
            message="Écart important avec des pièces similaires",
        ),
        BorneControle(
            champ="marge",
            min=0.05,
            max=0.50,
            niveau="alerte",
            message="Marge hors politique commerciale",
        ),
    ]
    for b in bornes:
        session.merge(b)
    session.commit()
