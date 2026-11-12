"""Tests du modèle 3D (issue #8).

Invariant central : la longueur de la ligne médiane du profil est égale à la
longueur développée du flan calculée par ``geometrie`` (mêmes données).
Références chiffrées : docs/logique_metier.md §8 (piece_support, « SUPPORT »).
"""

from __future__ import annotations

import pytest

from generateur_devis.geometrie import ErreurGeometrie, construire_flan
from generateur_devis.modele3d import (
    construire_modele_3d,
    construire_profil_2d,
    extruder_profil,
    longueur_ligne,
)
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
)

DENSITE_ACIER = 7.85
FACTEUR_K = 0.40


def piece_support() -> PieceExtraite:
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
    )


def _piece(elements: list, cotation: str = "exterieure", rayon: float | None = 2.0) -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation=cotation, rayon_pliage_general=rayon, elements=elements
        ),
    )


# --- Profil 2D ----------------------------------------------------------------


def test_profil_piece_support_forme_z():
    """Z : horizontal → vertical (pli haut) → horizontal opposé (pli bas).

    §8 : BD = 3,60 mm → segments 42−1,8 / 22−3,6 / 18−1,8 = 40,2 / 18,4 / 16,2.
    """
    points = construire_profil_2d(piece_support(), FACTEUR_K)
    assert len(points) == 4
    assert points[0] == pytest.approx((0.0, 0.0))
    assert points[1] == pytest.approx((40.2, 0.0), abs=0.01)
    assert points[2] == pytest.approx((40.2, 18.4), abs=0.01)
    assert points[3] == pytest.approx((56.4, 18.4), abs=0.01)


def test_invariant_longueur_developpee_piece_support():
    """Longueur de la ligne médiane = développé du flan (74,8 mm, §8)."""
    piece = piece_support()
    points = construire_profil_2d(piece, FACTEUR_K)
    flan = construire_flan(piece, DENSITE_ACIER, FACTEUR_K)
    assert longueur_ligne(points) == pytest.approx(flan.longueur_developpee_mm, abs=0.01)


def test_invariant_cotation_interieure():
    """Le même invariant tient en cotation intérieure (Σ ailes + Σ BA)."""
    piece = _piece(
        [Aile(longueur=30.0), Pli(angle=90.0, sens="haut"), Aile(longueur=20.0)],
        cotation="interieure",
    )
    points = construire_profil_2d(piece, FACTEUR_K)
    flan = construire_flan(piece, DENSITE_ACIER, FACTEUR_K)
    assert longueur_ligne(points) == pytest.approx(flan.longueur_developpee_mm, abs=0.01)


def test_piece_plate():
    """Pièce plate : une ligne horizontale de la longueur de l'aile."""
    points = construire_profil_2d(_piece([Aile(longueur=75.0)]), FACTEUR_K)
    assert points[0] == pytest.approx((0.0, 0.0))
    assert points[1] == pytest.approx((75.0, 0.0))


def test_profil_en_l():
    """L : montée verticale après le pli haut."""
    piece = _piece([Aile(longueur=50.0), Pli(angle=90.0, sens="haut"), Aile(longueur=30.0)])
    points = construire_profil_2d(piece, FACTEUR_K)
    # BD/2 ≈ 1,80 retranché à chaque extrémité pliée
    assert points[1] == pytest.approx((48.2, 0.0), abs=0.01)
    assert points[2] == pytest.approx((48.2, 28.2), abs=0.01)


def test_profil_qui_se_croise_erreur():
    """Profil en boucle (2 × 135°) : les segments non consécutifs se croisent."""
    piece = _piece(
        [
            Aile(longueur=30.0),
            Pli(angle=135.0, sens="haut"),
            Aile(longueur=30.0),
            Pli(angle=135.0, sens="haut"),
            Aile(longueur=30.0),
        ]
    )
    with pytest.raises(ErreurGeometrie, match="se croise"):
        construire_profil_2d(piece, FACTEUR_K)


# --- Maillage extrudé ----------------------------------------------------------


def test_modele_3d_piece_support():
    """Maillage : 2 rangées de sommets (y = 0 et y = 60), 3 faces (3 segments)."""
    maillage = construire_modele_3d(piece_support(), FACTEUR_K)
    assert len(maillage.sommets) == 8
    assert len(maillage.faces) == 3
    assert maillage.epaisseur_mm == 2.0
    ys = {s[1] for s in maillage.sommets}
    assert ys == {0.0, 60.0}
    for face in maillage.faces:
        assert len(face) == 4
        assert all(0 <= i < 8 for i in face)


def test_extruder_profil_largeur_invalide():
    with pytest.raises(ErreurGeometrie, match="Largeur d'extrusion invalide"):
        extruder_profil([(0.0, 0.0), (10.0, 0.0)], 0.0, 2.0)


# --- Erreurs ---------------------------------------------------------------------


def test_profil_absent_erreur():
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
    )
    with pytest.raises(ErreurGeometrie, match="Profil de pliage absent"):
        construire_modele_3d(piece, FACTEUR_K)


def test_cotation_inconnue_erreur():
    piece = _piece(
        [Aile(longueur=30.0), Pli(angle=90.0), Aile(longueur=20.0)], cotation="inconnue"
    )
    with pytest.raises(ErreurGeometrie, match="Cotation du profil inconnue") as exc:
        construire_profil_2d(piece, FACTEUR_K)
    assert "BA" not in str(exc.value) and "BD" not in str(exc.value)
    assert "extérieur" in str(exc.value) and "intérieur" in str(exc.value)


def test_rayon_non_cote_erreur():
    piece = _piece([Aile(longueur=30.0), Pli(angle=90.0), Aile(longueur=20.0)], rayon=None)
    with pytest.raises(ErreurGeometrie, match="Rayon de pliage non coté"):
        construire_profil_2d(piece, FACTEUR_K)


def test_largeur_absente_erreur():
    piece = piece_support()
    piece.encombrement.largeur = Champ[float](valeur=None)
    with pytest.raises(ErreurGeometrie, match="Largeur d'encombrement absente"):
        construire_modele_3d(piece, FACTEUR_K)


# --- Alternance aile / pli (issue #65) ----------------------------------------


@pytest.mark.parametrize(
    "elements",
    [
        [Aile(longueur=42.0), Aile(longueur=22.0), Pli(angle=90.0), Aile(longueur=18.0)],
        [],
    ],
    ids=["pli supprimé", "vide"],
)
def test_profil_incoherent_erreur_geometrie(elements):
    """Plus d'IndexError : un profil non alterné ou vide lève ErreurGeometrie."""
    with pytest.raises(ErreurGeometrie, match="incohérent"):
        construire_profil_2d(_piece(elements), FACTEUR_K)
