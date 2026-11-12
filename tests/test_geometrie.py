"""Tests du module géométrie (issue #7).

Les valeurs de référence viennent de docs/logique_metier.md §8 (piece_support,
« SUPPORT ») : elles sont recalculées indépendamment du module — les tests
appellent les fonctions de ``geometrie`` et comparent aux chiffres du document.
"""

from __future__ import annotations

import math

import pytest

from generateur_devis.geometrie import (
    ErreurGeometrie,
    aire_polygone_shoelace,
    aire_trou,
    calculer_ba,
    calculer_bd,
    construire_flan,
    longueur_developpee,
    perimetre_polygone,
    perimetre_trou,
    verifier_alternance,
)
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

# --- Référence piece_support (§8) ------------------------------------------------

DENSITE_ACIER = 7.85  # kg/dm³ (seedée en base, passée ici en paramètre)
FACTEUR_K = 0.40  # paramètre global « facteur_k » de la base


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


# --- Formule du développé ----------------------------------------------------


def test_ba_piece_support():
    """§8 : BA = π/2 × (2 + 0,4 × 2) = 4,40 mm."""
    assert calculer_ba(90.0, 2.0, 2.0, FACTEUR_K) == pytest.approx(4.40, abs=0.01)


def test_bd_piece_support():
    """§8 : BD = 2 × (2 + 2) − 4,40 = 3,60 mm."""
    assert calculer_bd(90.0, 2.0, 2.0, FACTEUR_K) == pytest.approx(3.60, abs=0.01)


def test_developpe_piece_support():
    """§8 : développé = 42 + 22 + 18 − 2 × 3,60 = 74,8 ≈ 75 mm."""
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    assert flan.longueur_developpee_mm == pytest.approx(74.8, abs=0.1)


def test_developpe_cotation_interieure():
    """Cotes intérieures : Σ ailes + Σ BA (même pièce, cotation intérieure)."""
    piece = piece_support()
    assert piece.profil_pliage is not None
    piece.profil_pliage.cotation = "interieure"
    # 82 + 2 × 4,40 = 90,8 mm
    flan = construire_flan(piece, DENSITE_ACIER, FACTEUR_K)
    assert flan.longueur_developpee_mm == pytest.approx(90.8, abs=0.1)


def test_piece_plate():
    """Une pièce plate (une seule aile) : développé = longueur de l'aile."""
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(cotation="inconnue", elements=[Aile(longueur=75.0)]),
    )
    flan = construire_flan(piece, DENSITE_ACIER, FACTEUR_K)
    assert flan.longueur_developpee_mm == pytest.approx(75.0)


# --- Flan de piece_support : surfaces, masses, coupe, amorçages ------------------


def test_masse_flan_piece_support():
    """§8 : masse flan = 4 500 × 2 × 7,85·10⁻⁶ ≈ 0,071 kg (rectangle englobant)."""
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    assert flan.surface_englobant_mm2 == pytest.approx(74.8 * 60, rel=0.01)
    assert flan.masse_flan_kg == pytest.approx(0.071, abs=0.002)


def test_surface_nette_piece_support():
    """Surface nette = englobant − trous − chanfreins (recalcul document)."""
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    attendu = (
        74.8 * 60
        - (2 * math.pi * (8.75 / 2) ** 2 + 2 * math.pi * (7.5 / 2) ** 2)
        - (2 * 20 * 20 / 2 + 2 * 5 * 5 / 2)
    )
    assert flan.surface_nette_mm2 == pytest.approx(attendu, rel=0.01)
    assert flan.masse_nette_kg == pytest.approx(attendu * 2 * DENSITE_ACIER * 1e-6, rel=0.01)


def test_longueur_coupe_piece_support():
    """§8 : contour ≈ 241 mm (chanfreins déduits) + trous ≈ 102 mm → ≈ 343 mm."""
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    assert flan.longueur_coupe_mm == pytest.approx(343.0, abs=3.0)


def test_nombre_amorcages_piece_support():
    """§8 : 5 amorçages = 1 contour + 4 trous (les quantités comptent)."""
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    assert flan.nombre_amorcages == 5


def test_polygone_est_rectangle_englobant():
    flan = construire_flan(piece_support(), DENSITE_ACIER, FACTEUR_K)
    assert aire_polygone_shoelace(flan.polygone_englobant) == pytest.approx(
        flan.surface_englobant_mm2
    )
    assert perimetre_polygone(flan.polygone_englobant) == pytest.approx(
        2 * (flan.longueur_developpee_mm + flan.largeur_mm)
    )


# --- Aires et périmètres des trous -------------------------------------------


def test_aire_trou_oblong():
    """Oblong (longueur hors tout) : rectangle central + 2 demi-cercles."""
    trou = Trou(forme="oblong", longueur=8.0, largeur=4.0)
    assert aire_trou(trou) == pytest.approx((8.0 - 4.0) * 4.0 + math.pi * 4.0)
    assert perimetre_trou(trou) == pytest.approx(2 * (8.0 - 4.0) + math.pi * 4.0)


def test_aire_trou_carre_et_rectangulaire():
    assert aire_trou(Trou(forme="carre", longueur=5.0, largeur=5.0)) == pytest.approx(25.0)
    assert aire_trou(Trou(forme="rectangulaire", longueur=6.0, largeur=3.0)) == pytest.approx(18.0)


def test_aire_trou_quantite():
    trou = Trou(forme="rond", diametre=8.75, quantite=2)
    assert aire_trou(trou) == pytest.approx(2 * math.pi * (8.75 / 2) ** 2)


def test_trou_autre_erreur():
    with pytest.raises(ErreurGeometrie, match="forme « autre »"):
        aire_trou(Trou(forme="autre"))


def test_trou_sans_dimensions_erreur():
    with pytest.raises(ErreurGeometrie, match="sans longueur/largeur"):
        aire_trou(Trou(forme="rectangulaire"))


# --- Erreurs de construction --------------------------------------------------


def test_profil_absent_erreur():
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
    )
    with pytest.raises(ErreurGeometrie, match="Profil de pliage absent"):
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)


def test_cotation_inconnue_erreur():
    piece = piece_support()
    assert piece.profil_pliage is not None
    piece.profil_pliage.cotation = "inconnue"
    with pytest.raises(ErreurGeometrie, match="Cotation du profil inconnue") as exc:
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)
    # Message lisible par un deviseur : pas de jargon BA/BD (#69).
    assert "BA" not in str(exc.value) and "BD" not in str(exc.value)
    assert "extérieur" in str(exc.value) and "intérieur" in str(exc.value)


def test_rayon_non_cote_erreur():
    piece = piece_support()
    assert piece.profil_pliage is not None
    piece.profil_pliage.rayon_pliage_general = None
    with pytest.raises(ErreurGeometrie, match="Rayon de pliage non coté"):
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)


def test_epaisseur_absente_erreur():
    piece = piece_support()
    piece.matiere.epaisseur = Champ[float](valeur=None)
    with pytest.raises(ErreurGeometrie, match="Épaisseur de tôle absente"):
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)


def test_largeur_absente_erreur():
    piece = piece_support()
    piece.encombrement.largeur = Champ[float](valeur=None)
    with pytest.raises(ErreurGeometrie, match="Largeur d'encombrement absente"):
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)


def test_cotes_contradictoires_erreur():
    """Cotes extérieures dont la somme des BD dépasse les ailes → développé négatif."""
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=1.0),
                Pli(angle=90.0),
                Aile(longueur=1.0),
                Pli(angle=90.0),
                Aile(longueur=1.0),
            ],
        ),
    )
    with pytest.raises(ErreurGeometrie, match="Cotes contradictoires"):
        construire_flan(piece, DENSITE_ACIER, FACTEUR_K)


def test_densite_invalide_erreur():
    with pytest.raises(ErreurGeometrie, match="Densité invalide"):
        construire_flan(piece_support(), 0.0, FACTEUR_K)


# --- Alternance aile / pli (issue #65) ----------------------------------------


def _piece_profil(elements: list) -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure", rayon_pliage_general=2.0, elements=elements
        ),
    )


PROFILS_INCOHERENTS = {
    "pli supprimé": [Aile(longueur=42.0), Aile(longueur=22.0), Pli(angle=90.0), Aile(longueur=18.0)],
    "vide": [],
    "finit par un pli": [Aile(longueur=42.0), Pli(angle=90.0)],
    "commence par un pli": [Pli(angle=90.0), Aile(longueur=42.0)],
}


@pytest.mark.parametrize("elements", PROFILS_INCOHERENTS.values(), ids=PROFILS_INCOHERENTS.keys())
def test_longueur_developpee_profil_incoherent(elements):
    with pytest.raises(ErreurGeometrie, match="incohérent"):
        longueur_developpee(_piece_profil(elements), FACTEUR_K)


def test_verifier_alternance_profils_valides():
    verifier_alternance(piece_support().profil_pliage)
    verifier_alternance(ProfilPliage(elements=[Aile(longueur=75.0)]))
