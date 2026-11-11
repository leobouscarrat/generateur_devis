"""Tests de l'écran de validation : rechiffrer et rendu 3D (issue #24).

Fonctions pures uniquement (pas de Streamlit) : ``rechiffrer`` enchaîne
géométrie → faisabilité → chiffrage → contrôles sur une pièce modifiée, et
``maillage_vers_figure`` convertit le maillage en figure plotly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.modele3d import construire_modele_3d
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
from generateur_devis.ui.app import _valider_lignes
from generateur_devis.ui.pipeline import rechiffrer
from generateur_devis.ui.rendu3d import maillage_vers_figure

MATIERE = "S235JR"
FACTEUR_K = 0.40


def piece_support(matiere: str | None = None) -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures."""
    return PieceExtraite(
        matiere=Matiere(designation=Champ[str](valeur=matiere), epaisseur=Champ[float](valeur=2.0)),
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


def test_rechiffrer_piece_inalteree(session):
    """Rechiffrer la pièce extraite telle quelle redonne le chiffrage provisoire."""
    resultat = rechiffrer(piece_support(MATIERE), MATIERE, None, None, session)
    assert resultat.erreur is None
    assert resultat.chiffrage is not None
    palier_100 = next(p for p in resultat.chiffrage.paliers if p.quantite == 100)
    assert palier_100.cout_unitaire_eur == pytest.approx(1.25, abs=0.03)


def test_rechiffrer_modification_epaisseur(session):
    """Une épaisseur modifiée change le chiffrage (recalcul à chaque modification)."""
    piece = piece_support(MATIERE).model_copy(deep=True)
    piece.matiere.epaisseur.valeur = 3.0
    resultat = rechiffrer(piece, MATIERE, None, [100], session)
    assert resultat.erreur is None
    assert resultat.chiffrage is not None
    # 3 mm au lieu de 2 : matière et coupe plus chères.
    assert resultat.chiffrage.paliers[0].cout_unitaire_eur > 1.25


def test_rechiffrer_blocage_faisabilite(session):
    """Épaisseur hors gamme → blocage, pas de chiffrage (validation impossible)."""
    piece = piece_support(MATIERE).model_copy(deep=True)
    piece.matiere.epaisseur.valeur = 7.0
    resultat = rechiffrer(piece, MATIERE, None, None, session)
    assert resultat.bloque
    assert resultat.chiffrage is None


def test_rechiffrer_matiere_inconnue(session):
    resultat = rechiffrer(piece_support(), "UNOBTANIUM", None, None, session)
    assert resultat.erreur is not None
    assert "Matière inconnue" in resultat.erreur
    assert resultat.chiffrage is None


def test_rechiffrer_client_marge_specifique(session):
    resultat = rechiffrer(piece_support(MATIERE), MATIERE, "CLI001", [100], session)
    palier = resultat.chiffrage.paliers[0]
    assert palier.prix_unitaire_eur == pytest.approx(palier.cout_unitaire_eur / 0.82, rel=1e-9)


def test_maillage_vers_figure(session):
    """Le maillage du SUPPORT donne une figure Mesh3d triangulée, axes en mm."""
    maillage = construire_modele_3d(piece_support(MATIERE), FACTEUR_K)
    figure = maillage_vers_figure(maillage)
    assert figure is not None
    mesh = figure.data[0]
    assert mesh.type == "mesh3d"
    # Faces quadrilatères scindées : 2 triangles par face.
    assert len(mesh.i) == 2 * len(maillage.faces)


def test_maillage_vers_figure_vide():
    assert maillage_vers_figure(None) is None


# --- Validation des lignes du formulaire (pas de suppression silencieuse) ----


def test_valider_lignes_valides():
    profil = [
        {"type": "aile", "longueur": 42.0, "angle": None, "sens": None},
        {"type": "pli", "longueur": None, "angle": 90.0, "sens": "haut"},
        {"type": None, "longueur": None, "angle": None, "sens": None},  # ligne vide ignorée
    ]
    trous = [{"forme": "rond", "diametre": 8.75, "quantite": 2}]
    assert _valider_lignes(profil, trous) == []


def test_valider_lignes_aile_sans_longueur():
    """Une aile sans longueur est une erreur explicite, pas une suppression."""
    profil = [{"type": "aile", "longueur": None, "angle": None, "sens": None}]
    erreurs = _valider_lignes(profil, [])
    assert len(erreurs) == 1
    assert "aile" in erreurs[0]


def test_valider_lignes_pli_incomplet():
    erreurs = _valider_lignes(
        [{"type": "pli", "longueur": None, "angle": None, "sens": "gauche"}], []
    )
    assert len(erreurs) == 2  # angle manquant + sens invalide


def test_valider_lignes_type_inconnu():
    erreurs = _valider_lignes(
        [{"type": "courbe", "longueur": 10.0, "angle": None, "sens": None}], []
    )
    assert len(erreurs) == 1
    assert "aile" in erreurs[0] and "pli" in erreurs[0]


def test_valider_lignes_trou_incomplet():
    erreurs = _valider_lignes([], [{"forme": "rond", "diametre": None, "quantite": 0}])
    assert len(erreurs) == 2  # diamètre manquant + quantité invalide
