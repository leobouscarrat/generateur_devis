"""Tests du moteur de règles de faisabilité (issue #9).

Base SQLite en mémoire seedée (même approche que ``test_data_acces.py``).
Les seuils viennent des paramètres seedés : ``regle_diam_trou_min_e`` = 1,0,
``regle_aile_min_e`` = 4,0, ``regle_rayon_min_e`` = 1,0 (× épaisseur).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.faisabilite import Constat, evaluer_faisabilite
from generateur_devis.geometrie import ErreurGeometrie
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
)

MATIERE = "S235JR"  # acier, épaisseurs dispo 1,0 à 4,0 mm (seed), format 3000 × 1500


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def piece_conforme() -> PieceExtraite:
    """Z conforme en tout point pour S235JR e=2 : ailes 40/30/20, R 2, trous Ø8."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=40.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=30.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=20.0),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.0)]),
    )


def regles(constats: list[Constat]) -> dict[str, str]:
    return {c.regle: c.severite for c in constats}


def test_piece_conforme_aucun_constat(session):
    assert evaluer_faisabilite(piece_conforme(), MATIERE, session) == []


def test_epaisseur_non_disponible_blocage(session):
    """S235JR n'a pas d'épaisseur 2,5 mm dans le seed → blocage."""
    piece = piece_conforme()
    piece.matiere.epaisseur = Champ[float](valeur=2.5)
    assert piece.profil_pliage is not None
    piece.profil_pliage.rayon_pliage_general = 4.0  # sinon rayon 2 < 2,5 déclenche rayon_min
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"epaisseur_dispo": "blocage"}


def test_flan_hors_format_blocage(session):
    """Développé ~90 mm × largeur 4 000 mm > tôle 3 000 × 1 500 → blocage."""
    piece = piece_conforme()
    piece.encombrement.largeur = Champ[float](valeur=4000.0)
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"flan_dans_format": "blocage"}


def test_flan_tient_dans_format_apres_rotation(session):
    """Le contrôle doit essayer les deux orientations : 2000 × 1000 tient dans 3000 × 1500."""
    piece = piece_conforme()
    piece.encombrement.largeur = Champ[float](valeur=2000.0)
    assert evaluer_faisabilite(piece, MATIERE, session) == []


def test_diametre_trou_trop_petit_alerte(session):
    """Ø1,5 mm < 1,0 × e (2 mm) → alerte ; trou oblong non concerné par la règle."""
    piece = piece_conforme()
    piece.contours.trous = [
        Trou(forme="rond", diametre=1.5),
        Trou(forme="oblong", longueur=8.0, largeur=4.0),
    ]
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"diam_trou_min": "alerte"}
    assert constats[0].champ == "contours.trous[0]"


def test_aile_trop_courte_alerte(session):
    """Aile 5 mm < 4 × e (8 mm) → alerte (ailes 40 et 30 conformes)."""
    piece = piece_conforme()
    assert piece.profil_pliage is not None
    piece.profil_pliage.elements[-1] = Aile(longueur=5.0)
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"aile_min": "alerte"}


def test_rayon_trop_petit_alerte(session):
    """Rayon 1 mm < 1 × e (2 mm) → alerte."""
    piece = piece_conforme()
    assert piece.profil_pliage is not None
    piece.profil_pliage.rayon_pliage_general = 1.0
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"rayon_min": "alerte"}


def test_traitement_incompatible_alerte(session):
    """Anodisation (aluminium) sur acier S235JR → alerte."""
    piece = piece_conforme()
    piece.traitement = Traitement(type=Champ[str](valeur="anodisation"))
    constats = evaluer_faisabilite(piece, MATIERE, session)
    assert regles(constats) == {"traitement_compatible": "alerte"}


def test_traitement_compatible_aucun_constat(session):
    """Galvanisation (acier) sur S235JR → pas de constat."""
    piece = piece_conforme()
    piece.traitement = Traitement(type=Champ[str](valeur="galvanisation"))
    assert evaluer_faisabilite(piece, MATIERE, session) == []


def test_traitement_non_applicable(session):
    """Traitement « aucun » ou non renseigné → règle absente du résultat."""
    piece = piece_conforme()
    piece.traitement = Traitement(type=Champ[str](valeur="aucun"))
    assert evaluer_faisabilite(piece, MATIERE, session) == []


def test_matiere_inconnue_erreur(session):
    with pytest.raises(ErreurGeometrie, match="Matière inconnue"):
        evaluer_faisabilite(piece_conforme(), "UNOBTANIUM", session)


def test_constats_cumules(session):
    """Plusieurs règles déclenchées : toutes présentes, avec sévérités distinctes."""
    piece = piece_conforme()
    piece.matiere.epaisseur = Champ[float](valeur=2.5)  # blocage
    assert piece.profil_pliage is not None
    piece.profil_pliage.rayon_pliage_general = 4.0  # sinon rayon_min se déclenche aussi
    piece.contours.trous = [Trou(forme="rond", diametre=1.5)]  # alerte (e=2,5 → seuil 2,5)
    constats = evaluer_faisabilite(piece, MATIERE, session)
    attendu = {"epaisseur_dispo": "blocage", "diam_trou_min": "alerte"}
    assert regles(constats) == attendu
