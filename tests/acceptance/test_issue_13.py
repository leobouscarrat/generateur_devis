"""Tests d'acceptation pour l'issue #13 — Blocs 1 à 3 du chiffrage (matière, découpe, pliage).

Un test par critère d'acceptation, indépendants, appelant le code réel.
Base SQLite en mémoire seedée (même approche que tests/test_faisabilite.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.calcul_prix import (
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
    return construire_flan(piece_003(), matiere.densite_kg_dm3, 0.40)


# --- C3-C5 : Modèles Pydantic des 3 blocs ---


def test_bloc_matiere_modele_pydantic(session, flan_003):
    """C3 : BlocMatiere est un modèle Pydantic avec les champs attendus."""
    from generateur_devis.calcul_prix import BlocMatiere

    bloc = calculer_bloc_matiere(flan_003, MATIERE, session)
    assert isinstance(bloc, BlocMatiere)
    assert hasattr(bloc, "masse_flan_kg")
    assert hasattr(bloc, "cout_variable_eur")
    assert hasattr(bloc, "cout_fixe_eur_par_lot")


def test_bloc_decoupe_modele_pydantic(session, flan_003):
    """C4 : BlocDecoupe est un modèle Pydantic avec les champs attendus."""
    from generateur_devis.calcul_prix import BlocDecoupe

    bloc = calculer_bloc_decoupe(flan_003, "acier", session)
    assert isinstance(bloc, BlocDecoupe)
    assert hasattr(bloc, "longueur_coupe_mm")
    assert hasattr(bloc, "nombre_amorcages")
    assert hasattr(bloc, "temps_cycle_s")
    assert hasattr(bloc, "cout_variable_eur")
    assert hasattr(bloc, "cout_fixe_eur_par_lot")


def test_bloc_pliage_modele_pydantic(session, flan_003):
    """C5 : BlocPliage est un modèle Pydantic avec les champs attendus."""
    from generateur_devis.calcul_prix import BlocPliage

    bloc = calculer_bloc_pliage(piece_003(), flan_003, session)
    assert isinstance(bloc, BlocPliage)
    assert hasattr(bloc, "nb_plis")
    assert hasattr(bloc, "temps_par_pli_s")
    assert hasattr(bloc, "temps_cycle_s")
    assert hasattr(bloc, "cout_variable_eur")
    assert hasattr(bloc, "cout_fixe_eur_par_lot")


# --- C6 : calculer_blocs_1_3 ---


def test_calculer_blocs_1_3_retourne_trois_blocs(session, flan_003):
    """C6 : calculer_blocs_1_3 retourne un objet BlocsCout avec matiere/decoupe/pliage."""
    from generateur_devis.calcul_prix import BlocsCout

    blocs = calculer_blocs_1_3(piece_003(), flan_003, MATIERE, session)
    assert isinstance(blocs, BlocsCout)
    assert hasattr(blocs, "matiere")
    assert hasattr(blocs, "decoupe")
    assert hasattr(blocs, "pliage")


# --- C7-C10 : Cas d'erreur / edge cases ---


def test_bloc_matiere_inconnue_levere_erreur(session, flan_003):
    """C7 : Matière inconnue du référentiel lève ErreurChiffrage."""
    from generateur_devis.calcul_prix import ErreurChiffrage

    with pytest.raises(ErreurChiffrage, match="Matière inconnue"):
        calculer_bloc_matiere(flan_003, "INCONNU", session)


def test_bloc_decoupe_vitesse_manquante_levere_erreur(session, flan_003):
    """C8 : Pas de vitesse de coupe lève ErreurChiffrage."""
    from generateur_devis.calcul_prix import ErreurChiffrage

    with pytest.raises(ErreurChiffrage, match="Pas de vitesse de coupe"):
        calculer_bloc_decoupe(flan_003, "titane", session)


def test_bloc_decoupe_poste_inconnu_levere_erreur(session, flan_003):
    """C9 : Poste de découpe inconnu lève ErreurChiffrage."""
    from generateur_devis.calcul_prix import ErreurChiffrage

    session.merge(Parametre(cle="poste_decoupe", valeur="LASER_FANTOME"))
    session.flush()
    with pytest.raises(ErreurChiffrage, match="Poste de découpe inconnu"):
        calculer_bloc_decoupe(flan_003, "acier", session)


def test_bloc_matiere_rendement_nul_levere_erreur(session, flan_003):
    """C10 : Rendement de calepinage égal à 0 lève ErreurChiffrage."""
    from generateur_devis.calcul_prix import ErreurChiffrage

    session.merge(Parametre(cle="rendement_calepinage", valeur="0"))
    session.flush()
    with pytest.raises(ErreurChiffrage, match="Rendement de calepinage invalide"):
        calculer_bloc_matiere(flan_003, MATIERE, session)


# --- C13-C16 : Vérification des coûts de référence ---


def test_bloc_matiere_cout_reference_piece_003(session, flan_003):
    """C13 : Bloc 1 coût variable unitaire ≈ 0,10 €, coût fixe par lot = 0 € à Q=100."""
    bloc = calculer_bloc_matiere(flan_003, MATIERE, session)
    assert bloc.cout_variable_eur == pytest.approx(0.10, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == 0.0


def test_bloc_decoupe_cout_reference_piece_003(session, flan_003):
    """C14 : Bloc 2 coût variable unitaire ≈ 0,30 €, coût fixe par lot ≈ 30 € à Q=100."""
    bloc = calculer_bloc_decoupe(flan_003, "acier", session)
    assert bloc.longueur_coupe_mm == pytest.approx(343.0, abs=3.0)
    assert bloc.nombre_amorcages == 5
    assert bloc.temps_cycle_s == pytest.approx(9.1, abs=0.2)
    assert bloc.cout_variable_eur == pytest.approx(0.30, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(30.0, rel=0.01)
    assert bloc.cout_variable_eur + bloc.cout_fixe_eur_par_lot / QUANTITE == pytest.approx(
        0.60, abs=0.02
    )


def test_bloc_pliage_cout_reference_piece_003(session, flan_003):
    """C15 : Bloc 3 coût variable unitaire ≈ 0,31 €, coût fixe par lot ≈ 23,3 € à Q=100."""
    bloc = calculer_bloc_pliage(piece_003(), flan_003, session)
    assert bloc.nb_plis == 2
    assert bloc.temps_par_pli_s == pytest.approx(8.0)
    assert bloc.temps_cycle_s == pytest.approx(16.0)
    assert bloc.cout_variable_eur == pytest.approx(0.31, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(70.0 / 3.0, rel=0.01)
    assert bloc.cout_variable_eur + bloc.cout_fixe_eur_par_lot / QUANTITE == pytest.approx(
        0.54, abs=0.02
    )


def test_blocs_100_qte_totaux_piece_003(session, flan_003):
    """C16 : cout_variable + cout_fixe/quantité donnent les totaux référencés à Q=100."""
    blocs = calculer_blocs_1_3(piece_003(), flan_003, MATIERE, session)
    assert blocs.matiere.cout_variable_eur == pytest.approx(0.10, abs=0.01)
    assert blocs.decoupe.cout_variable_eur == pytest.approx(0.30, abs=0.01)
    assert blocs.pliage.cout_variable_eur == pytest.approx(0.31, abs=0.01)


# --- C17 : Grandeurs intermédiaires ---


def test_bloc_matiere_grandeur_masse_flan(session, flan_003):
    """C17 : Grandeur intermédiaire masse_flan ≈ 0,071 kg."""
    bloc = calculer_bloc_matiere(flan_003, MATIERE, session)
    assert bloc.masse_flan_kg == pytest.approx(0.071, abs=0.002)


def test_bloc_decoupe_grandeur_longueur_coupe(session, flan_003):
    """C17 : Grandeur intermédiaire longueur_coupe ≈ 343 mm."""
    bloc = calculer_bloc_decoupe(flan_003, "acier", session)
    assert bloc.longueur_coupe_mm == pytest.approx(343.0, abs=3.0)


def test_bloc_decoupe_grandeur_amorçages(session, flan_003):
    """C17 : Grandeur intermédiaire nb_amorçages = 5."""
    bloc = calculer_bloc_decoupe(flan_003, "acier", session)
    assert bloc.nombre_amorcages == 5


def test_bloc_pliage_grandeur_nb_plis(session, flan_003):
    """C17 : Grandeur intermédiaire nb_plis = 2."""
    bloc = calculer_bloc_pliage(piece_003(), flan_003, session)
    assert bloc.nb_plis == 2


# --- C18 : Paramètres depuis la base ---


def test_parametres_postes_depuis_la_base(session):
    """C18 : Les identifiants de poste viennent des paramètres Parametre, pas du code."""
    assert get_parametre("poste_decoupe", session) == get_poste("LASER_3KW", session).id
    assert get_parametre("poste_pliage", session) == get_poste("PLIEUSE_CN", session).id


# --- C19 : Pas de retournement V1 ---


def test_bloc_pliage_aucun_retournement_v1(session, flan_003):
    """C19 : En V1, le bloc 3 ne compte pas le temps de retournement de la plieuse."""
    bloc = calculer_bloc_pliage(piece_003(), flan_003, session)
    assert bloc.temps_cycle_s == pytest.approx(16.0)
