"""Tests du cycle de vie d'un devis (issue #22).

Base SQLite en mémoire seedée. Le devis de référence est construit sur
piece_003 (§8.3) : coût ≈ 2,20 € et prix ≈ 2,93 € à Q=100.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.calcul_prix import calculer_bloc_finition, chiffrer
from generateur_devis.data.acces import get_matiere
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.data.tables import Matiere as MatiereTable
from generateur_devis.devis import Devis, ErreurDevis, emettre
from generateur_devis.geometrie import construire_flan
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)

MATIERE = "S235JR"
FACTEUR_K = 0.40


def piece_003() -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(
            trous=[
                Trou(forme="rond", diametre=8.75, quantite=2),
                Trou(forme="rond", diametre=7.5, quantite=2),
            ],
            coins=[
                CoinCoupe(type="chanfrein", cote1=20.0, quantite=2),
                CoinCoupe(type="chanfrein", cote1=5.0, quantite=2),
            ],
        ),
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


@pytest.fixture
def flan_003(session):
    matiere = get_matiere(MATIERE, session)
    return construire_flan(piece_003(), matiere.densite_kg_dm3, FACTEUR_K)


@pytest.fixture
def devis_003(session, flan_003):
    """Devis piece_003 validé : Q commandée 100, marge 25 %, option peinture."""
    chiffrage = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)])
    option = calculer_bloc_finition(piece_003(), flan_003, session, traitement_id="PEINTURE_POUDRE")
    devis = Devis(
        id="D-2026-9001",
        client_id="CLI001",
        matiere_id=MATIERE,
        piece_validee=piece_003(),
        chiffrage=chiffrage,
        marge=0.25,
        options=[option] if option else [],
        quantite_commandee=100,
        auteur="charge_affaires",
        date_creation=datetime.now(),
    )
    devis.valider("charge_affaires")
    return devis


def test_devis_valide_piece_003(devis_003):
    assert devis_003.statut == "valide"
    palier = devis_003.palier_commande()
    assert palier.quantite == 100
    assert palier.cout_unitaire_eur == pytest.approx(2.20, abs=0.03)
    assert palier.prix_unitaire_eur == pytest.approx(2.93, abs=0.05)


def test_figeage_apres_validation(session, devis_003):
    """Un prix matière modifié en base après validation ne change pas le devis."""
    prix_avant = devis_003.palier_commande().prix_unitaire_eur
    session.merge(
        MatiereTable(
            id=MATIERE,
            famille="acier",
            densite_kg_dm3=7.85,
            prix_eur_kg=99.0,
            date_maj=get_matiere(MATIERE, session).date_maj,
        )
    )
    session.flush()
    assert devis_003.palier_commande().prix_unitaire_eur == prix_avant
    # Et la sérialisation reste identique
    assert (
        Devis.model_validate_json(devis_003.model_dump_json()).palier_commande().prix_unitaire_eur
        == prix_avant
    )


def test_changer_marge_rechiffre_depuis_couts_figes(devis_003):
    """Marge 25 % → 40 % : prix recalculé depuis le coût figé, coût inchangé."""
    cout = devis_003.palier_commande().cout_unitaire_eur
    devis_003.changer_marge("charge_affaires", 0.40)
    assert devis_003.palier_commande().cout_unitaire_eur == cout
    assert devis_003.palier_commande().prix_unitaire_eur == pytest.approx(cout / 0.60, rel=1e-9)
    modif = devis_003.modifications[-1]
    assert modif.champ == "marge"
    assert modif.avant == 0.25
    assert modif.apres == 0.40
    assert modif.auteur == "charge_affaires"


def test_changer_marge_invalide(devis_003):
    with pytest.raises(ErreurDevis, match="Marge invalide"):
        devis_003.changer_marge("charge_affaires", 1.5)


def test_journal_modifications(devis_003):
    """Validation + changement de marge : chaque action est journalisée."""
    devis_003.changer_marge("direction", 0.30)
    champs = [m.champ for m in devis_003.modifications]
    assert champs == ["statut", "marge"]
    assert devis_003.auteur == "direction"


def test_roundtrip_json(devis_003):
    clone = Devis.model_validate_json(devis_003.model_dump_json())
    assert clone == devis_003
    assert clone.chiffrage.trace  # la trace complète survit à la sérialisation


def test_emission_vers_historique(session, devis_003, flan_003):
    ligne = emettre(devis_003, flan_003, "charge_affaires", session)
    session.flush()
    assert devis_003.statut == "emis"
    assert devis_003.date_emission is not None
    assert ligne.id == "D-2026-9001"
    assert ligne.matiere_id == MATIERE
    assert ligne.quantite == 100
    assert ligne.cout_unitaire_eur == pytest.approx(2.20, abs=0.03)
    assert ligne.prix_unitaire_eur == pytest.approx(2.93, abs=0.05)
    assert ligne.flan_l_mm == pytest.approx(74.8, abs=0.1)
    assert ligne.flan_w_mm == pytest.approx(60.0)
    assert ligne.nb_trous == 4
    assert ligne.nb_plis == 2
    assert ligne.nb_composants == 0  # nomenclature extraite vide dans le fixture
    assert ligne.traitement_id == "PEINTURE_POUDRE"


def test_emission_exige_validation(session, flan_003):
    chiffrage = chiffrer(piece_003(), MATIERE, session)
    devis = Devis(
        id="D-2026-9002",
        matiere_id=MATIERE,
        piece_validee=piece_003(),
        chiffrage=chiffrage,
        marge=0.25,
        quantite_commandee=100,
        date_creation=datetime.now(),
    )
    with pytest.raises(ErreurDevis, match="validé avant émission"):
        emettre(devis, flan_003, "charge_affaires", session)


def test_devis_emis_en_lecture_seule(devis_003, flan_003, session):
    emettre(devis_003, flan_003, "charge_affaires", session)
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        devis_003.changer_marge("charge_affaires", 0.30)
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        devis_003.valider("charge_affaires")
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        emettre(devis_003, flan_003, "charge_affaires", session)


def test_palier_commande_absent(devis_003):
    devis_003.quantite_commandee = 42
    with pytest.raises(ErreurDevis, match="Aucun palier"):
        devis_003.palier_commande()
