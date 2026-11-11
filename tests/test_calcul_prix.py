"""Tests du moteur de chiffrage — blocs 1 à 3 (issue #13).

Base SQLite en mémoire seedée (même approche que ``test_faisabilite.py``).
Les valeurs attendues sont recalculées à la main depuis les données seedées
(lues via ``acces``) et confrontées aux montants de référence du
docs/logique_metier.md §8.3 (piece_003, montants unitaires à Q=100) :
bloc 1 = 0,10 €, bloc 2 = 0,30 € variable + 30 € de réglage/lot,
bloc 3 = 0,31 € variable + 23,3 € de réglage/lot.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.calcul_prix import (
    ErreurChiffrage,
    calculer_bloc_decoupe,
    calculer_bloc_matiere,
    calculer_bloc_pliage,
    calculer_blocs_1_3,
)
from generateur_devis.data.acces import get_matiere, get_parametre, get_poste
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, Parametre
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

MATIERE = "S235JR"  # acier 7,85 kg/dm³, 1,10 €/kg (seed)
QUANTITE = 100  # référence §8.3 : montants unitaires à Q=100
DENSITE_ACIER = 7.85
FACTEUR_K = 0.40  # paramètre « facteur_k » de la base


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


# --- Bloc 1 — Matière ---------------------------------------------------------


def test_bloc_matiere_piece_003(session, flan_003):
    """§8.3 : 0,071 kg ÷ 0,80 × 1,10 €/kg ≈ 0,10 €/pièce."""
    bloc = calculer_bloc_matiere(flan_003, MATIERE, session)
    matiere = get_matiere(MATIERE, session)
    rendement = float(get_parametre("rendement_calepinage", session))
    attendu = flan_003.masse_flan_kg / rendement * matiere.prix_eur_kg
    assert bloc.cout_variable_eur == pytest.approx(attendu, rel=1e-9)
    assert bloc.cout_variable_eur == pytest.approx(0.10, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == 0.0
    assert bloc.masse_flan_kg == pytest.approx(0.071, abs=0.002)


def test_bloc_matiere_inconnue(session, flan_003):
    with pytest.raises(ErreurChiffrage, match="Matière inconnue"):
        calculer_bloc_matiere(flan_003, "INCONNU", session)


def test_bloc_matiere_rendement_nul(session, flan_003):
    session.merge(Parametre(cle="rendement_calepinage", valeur="0"))
    session.flush()
    with pytest.raises(ErreurChiffrage, match="Rendement de calepinage invalide"):
        calculer_bloc_matiere(flan_003, MATIERE, session)


# --- Bloc 2 — Découpe ----------------------------------------------------------


def test_bloc_decoupe_piece_003(session, flan_003):
    """§8.3 : (0,343 m ÷ 5 m/min + 5 × 1 s) ≈ 9,1 s × 120 €/h ≈ 0,30 €/pièce
    + réglage 15 min × 120 €/h = 30 € de fixe par lot."""
    bloc = calculer_bloc_decoupe(flan_003, "acier", session)
    assert bloc.longueur_coupe_mm == pytest.approx(343.0, abs=3.0)
    assert bloc.nombre_amorcages == 5
    assert bloc.temps_cycle_s == pytest.approx(9.1, abs=0.2)
    assert bloc.cout_variable_eur == pytest.approx(0.30, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(30.0, rel=0.01)
    # §8.3 : 0,60 €/pièce à Q=100 = variable + réglage ÷ 100
    assert bloc.cout_variable_eur + bloc.cout_fixe_eur_par_lot / QUANTITE == pytest.approx(
        0.60, abs=0.02
    )


def test_bloc_decoupe_vitesse_manquante(session, flan_003):
    """Famille sans ligne dans vitesses_coupe → erreur explicite."""
    with pytest.raises(ErreurChiffrage, match="Pas de vitesse de coupe"):
        calculer_bloc_decoupe(flan_003, "titane", session)


def test_bloc_decoupe_poste_inconnu(session, flan_003):
    session.merge(Parametre(cle="poste_decoupe", valeur="LASER_FANTOME"))
    session.flush()
    with pytest.raises(ErreurChiffrage, match="Poste de découpe inconnu"):
        calculer_bloc_decoupe(flan_003, "acier", session)


# --- Bloc 3 — Pliage -----------------------------------------------------------


def test_bloc_pliage_piece_003(session, flan_003):
    """§8.3 : 2 plis × 8 s = 16 s × 70 €/h ≈ 0,31 €/pièce
    + réglage 20 min × 70 €/h ≈ 23,3 € de fixe par lot."""
    bloc = calculer_bloc_pliage(piece_003(), flan_003, session)
    assert bloc.nb_plis == 2
    assert bloc.temps_par_pli_s == pytest.approx(8.0)  # tranche « petite » seedée
    assert bloc.temps_cycle_s == pytest.approx(16.0)
    assert bloc.cout_variable_eur == pytest.approx(0.31, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(70.0 / 3.0, rel=0.01)
    # §8.3 : 0,54 €/pièce à Q=100
    assert bloc.cout_variable_eur + bloc.cout_fixe_eur_par_lot / QUANTITE == pytest.approx(
        0.54, abs=0.02
    )


def test_bloc_pliage_piece_plate(session):
    """Pièce sans pli : bloc 3 à zéro, sans réglage."""
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(cotation="inconnue", elements=[Aile(longueur=75.0)]),
    )
    matiere = get_matiere(MATIERE, session)
    flan = construire_flan(piece, matiere.densite_kg_dm3, FACTEUR_K)
    bloc = calculer_bloc_pliage(piece, flan, session)
    assert bloc.nb_plis == 0
    assert bloc.cout_variable_eur == 0.0
    assert bloc.cout_fixe_eur_par_lot == 0.0


def test_bloc_pliage_grande_piece(session):
    """Le temps par pli suit la tranche de la table temps_pliage."""
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=5.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=600.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=5.0,
            elements=[Aile(longueur=100.0), Pli(angle=90.0), Aile(longueur=100.0)],
        ),
    )
    matiere = get_matiere(MATIERE, session)
    flan = construire_flan(piece, matiere.densite_kg_dm3, FACTEUR_K)
    bloc = calculer_bloc_pliage(piece, flan, session)
    assert bloc.temps_par_pli_s == pytest.approx(20.0)  # tranche « moyenne » e ≤ 10


# --- Orchestrateur des trois blocs --------------------------------------------


def test_calculer_blocs_1_3_piece_003(session, flan_003):
    blocs = calculer_blocs_1_3(piece_003(), flan_003, MATIERE, session)
    assert blocs.matiere.cout_variable_eur == pytest.approx(0.10, abs=0.01)
    assert blocs.decoupe.cout_variable_eur == pytest.approx(0.30, abs=0.01)
    assert blocs.pliage.cout_variable_eur == pytest.approx(0.31, abs=0.01)


def test_calculer_blocs_1_3_matiere_inconnue(session, flan_003):
    with pytest.raises(ErreurChiffrage, match="Matière inconnue"):
        calculer_blocs_1_3(piece_003(), flan_003, "INCONNU", session)


def test_parametres_postes_depuis_la_base(session):
    """Les identifiants de poste viennent des paramètres, pas du code."""
    assert get_parametre("poste_decoupe", session) == get_poste("LASER_3KW", session).id
    assert get_parametre("poste_pliage", session) == get_poste("PLIEUSE_CN", session).id
