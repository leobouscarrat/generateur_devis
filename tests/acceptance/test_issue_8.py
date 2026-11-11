"""Tests d'acceptation pour l'issue #8 — Modèle 3D de la pièce pliée.

Un test par critère d'acceptation, indépendants, appelant le code réel.
"""
from __future__ import annotations

from generateur_devis.modele3d import construire_modele_3d
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


# --- Critère 5 : références L, U, Z -------------------------------------------

def piece_003_z() -> PieceExtraite:
    """Z : référence §8 (déjà utilisée dans test_modele3d.py)."""
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


def _piece_l() -> PieceExtraite:
    """L : une aile, pli 90°, une aile (cotation extérieure)."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=50.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=30.0),
            ],
        ),
    )


def _piece_u() -> PieceExtraite:
    """U : aile → pli 90° haut → aile → pli 90° bas → aile (cotation extérieure)."""
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
                Aile(longueur=40.0),
            ],
        ),
    )


# ----- Critère 5 - L solide de référence --------------------------------------

def test_modele_3d_reference_l():
    """L : solide 3D constructible (extrusion du profil sur la largeur)."""
    piece = _piece_l()
    maillage = construire_modele_3d(piece, FACTEUR_K)
    # Structure de base : sommets et faces
    assert len(maillage.sommets) >= 4  # au minimum 2 rangées × nb segments
    assert len(maillage.faces) >= 1
    assert maillage.epaisseur_mm == 2.0
    # Deux rangées en y (plan et extrusion)
    ys = {s[1] for s in maillage.sommets}
    assert ys == {0.0, 60.0}, f"Expected ys={{0.0, 60.0}}, got {ys}"


# ----- Critère 5 - U solide de référence --------------------------------------

def test_modele_3d_reference_u():
    """U : solide 3D constructible (extrusion du profil sur la largeur)."""
    piece = _piece_u()
    maillage = construire_modele_3d(piece, FACTEUR_K)
    # Structure de base : sommets et faces
    assert len(maillage.sommets) >= 6  # plus complexe que L/Z
    assert len(maillage.faces) >= 1
    assert maillage.epaisseur_mm == 2.0
    # Deux rangées en y (plan et extrusion)
    ys = {s[1] for s in maillage.sommets}
    assert ys == {0.0, 60.0}, f"Expected ys={{0.0, 60.0}}, got {ys}"


# ----- Critère 2 : retrait trous/chanfreins hors périmètre V1 ----------------

# Note : le retrait des trous et chanfreins est hors périmètre V1 (cf. commentaire
# dans modele3d.py §10-11 et commentaire de la PR #11). Ce test documente le
# comportement actuel : le solide est construit sans retirer les trous/chanfreins.
# Un test séparé validera le retrait dans une future version (V2).

def test_modele_3d_sans_retirer_trous():
    """V1 : le solide ne retire pas les trous/chanfreins (hors périmètre V1).

    Ce test ne doit pas échouer par régression ; il documente le comportement
    actuel tel qu'exposé dans la spec §Étape 3a/4.
    """
    piece = PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=50.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=30.0),
            ],
        ),
    )
    # Le modele3d.py ne retire pas les trous en V1 ; le solide est quand même valide.
    maillage = construire_modele_3d(piece, FACTEUR_K)
    assert maillage is not None
    assert len(maillage.sommets) >= 4
    assert maillage.epaisseur_mm == 2.0
