"""Tests du cycle de vie d'un devis (issue #22).

Base SQLite en mémoire seedée. Le devis de référence est construit sur
piece_003 (§8.3) : coût ≈ 2,20 € et prix ≈ 2,93 € à Q=100.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError
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
from generateur_devis.ui.pipeline import ResultatDevis, rechiffrer

MATIERE = "S235JR"
FACTEUR_K = 0.40


def piece_003(largeur: float = 60.0, epaisseur: float = 2.0) -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures.

    Matière non désignée (cas réel de l'issue #54 : non lue sur le plan).
    """
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=epaisseur)),
        encombrement=Encombrement(largeur=Champ[float](valeur=largeur)),
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
        flan=flan_003,
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
    ligne = emettre(devis_003, "charge_affaires", session)
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
        flan=flan_003,
        marge=0.25,
        quantite_commandee=100,
        date_creation=datetime.now(),
    )
    with pytest.raises(ErreurDevis, match="validé avant émission"):
        emettre(devis, "charge_affaires", session)


def test_devis_emis_en_lecture_seule(devis_003, session):
    emettre(devis_003, "charge_affaires", session)
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        devis_003.changer_marge("charge_affaires", 0.30)
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        devis_003.valider("charge_affaires")
    with pytest.raises(ErreurDevis, match="plus modifiable"):
        emettre(devis_003, "charge_affaires", session)


def test_palier_commande_absent(devis_003):
    devis_003.quantite_commandee = 42
    with pytest.raises(ErreurDevis, match="Aucun palier"):
        devis_003.palier_commande()


# ---------------------------------------------------------------------------
# Issue #54 : le devis porte le flan de la pièce validée
# ---------------------------------------------------------------------------


def _devis(piece: PieceExtraite, chiffrage, flan) -> Devis:
    return Devis(
        id="D-2026-0054",
        matiere_id=MATIERE,
        piece_validee=piece,
        chiffrage=chiffrage,
        flan=flan,
        marge=0.25,
        quantite_commandee=100,
        date_creation=datetime.now(),
    )


def test_emission_matiere_absente_du_depot(session):
    """Cas de l'issue : matière non lue au dépôt → flan initial absent ;
    la matière choisie à la validation suffit à émettre."""
    depot = ResultatDevis(piece=piece_003(), matiere_id=None)
    assert depot.flan is None  # c'est ce flan que l'émission relisait

    resultat = rechiffrer(piece_003(), MATIERE, None, [100], session)
    devis = _devis(piece_003(), resultat.chiffrage, resultat.flan)
    devis.valider("testeur")
    ligne = emettre(devis, "testeur", session)
    session.flush()

    assert devis.statut == "emis"
    # §8 : flan 74,8 × 60 mm, e = 2 mm ; masse = 74,8 × 60 × 2 × 7,85e-6 ≈ 0,0705 kg.
    assert ligne.flan_w_mm == pytest.approx(60.0)
    assert ligne.flan_l_mm == pytest.approx(74.8, abs=0.1)
    assert ligne.epaisseur_mm == pytest.approx(2.0)
    assert ligne.masse_kg == pytest.approx(0.0705, abs=0.001)


def test_emission_flan_piece_corrigee(session):
    """Largeur corrigée 60 → 80 à la validation : la ligne émise suit la pièce validée."""
    matiere = get_matiere(MATIERE, session)
    flan_initial = construire_flan(piece_003(), matiere.densite_kg_dm3, FACTEUR_K)
    assert flan_initial.largeur_mm == pytest.approx(60.0)

    piece_80 = piece_003(largeur=80.0)
    resultat = rechiffrer(piece_80, MATIERE, None, [100], session)

    # Reproduction exacte du défaut : flan initial + pièce validée → refusé.
    with pytest.raises(ValidationError, match="Flan incohérent"):
        _devis(piece_80, resultat.chiffrage, flan_initial)

    devis = _devis(piece_80, resultat.chiffrage, resultat.flan)
    devis.valider("testeur")
    ligne = emettre(devis, "testeur", session)
    assert ligne.flan_w_mm == pytest.approx(80.0)
    # Masse au rectangle englobant : 74,8 × 80 × 2 × 7,85e-6 ≈ 0,0939 kg.
    assert ligne.masse_kg == pytest.approx(0.0939, abs=0.001)


def test_flan_incoherent_epaisseur(session):
    """Pièce validée à 3 mm, flan calculé à 2 mm → ValidationError explicite."""
    matiere = get_matiere(MATIERE, session)
    flan_2mm = construire_flan(piece_003(), matiere.densite_kg_dm3, FACTEUR_K)
    piece_3mm = piece_003(epaisseur=3.0)
    chiffrage = chiffrer(piece_3mm, MATIERE, session)
    with pytest.raises(ValidationError, match="Flan incohérent.*épaisseur"):
        _devis(piece_3mm, chiffrage, flan_2mm)


def test_devis_sans_flan_refuse(session):
    """Le flan est obligatoire : un Devis sans flan ne peut pas exister."""
    chiffrage = chiffrer(piece_003(), MATIERE, session)
    with pytest.raises(ValidationError, match="flan"):
        Devis(
            id="D-2026-0055",
            matiere_id=MATIERE,
            piece_validee=piece_003(),
            chiffrage=chiffrage,
            marge=0.25,
            quantite_commandee=100,
            date_creation=datetime.now(),
        )


def test_roundtrip_json_conserve_le_flan(devis_003, flan_003):
    clone = Devis.model_validate_json(devis_003.model_dump_json())
    assert clone.flan == flan_003


# --- Bornes de la marge : règle unique de Devis.changer_marge (issue #62) -------


def test_changer_marge_096_acceptee(devis_003):
    """0,96 dépasse l'ancienne borne du widget (0,95) mais respecte 0 ≤ marge < 1."""
    cout = devis_003.palier_commande().cout_unitaire_eur
    devis_003.changer_marge("charge_affaires", 0.96)
    assert devis_003.marge == 0.96
    assert devis_003.palier_commande().prix_unitaire_eur == pytest.approx(cout / 0.04, rel=1e-9)


def test_changer_marge_zero_acceptee(devis_003):
    """Borne basse incluse : prix = coût."""
    cout = devis_003.palier_commande().cout_unitaire_eur
    devis_003.changer_marge("charge_affaires", 0.0)
    assert devis_003.marge == 0.0
    assert devis_003.palier_commande().prix_unitaire_eur == pytest.approx(cout, rel=1e-9)


@pytest.mark.parametrize("marge", [1.0, -0.01])
def test_changer_marge_hors_bornes_sans_effet(devis_003, marge):
    """Marge refusée : ni marge, ni prix, ni journal ne changent."""
    prix = [p.prix_unitaire_eur for p in devis_003.chiffrage.paliers]
    nb_modifications = len(devis_003.modifications)
    with pytest.raises(ErreurDevis, match="Marge invalide"):
        devis_003.changer_marge("charge_affaires", marge)
    assert devis_003.marge == 0.25
    assert [p.prix_unitaire_eur for p in devis_003.chiffrage.paliers] == prix
    assert len(devis_003.modifications) == nb_modifications
