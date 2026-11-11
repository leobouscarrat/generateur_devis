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
from generateur_devis.ui.app import (
    CLE_CONTEXTE,
    CLE_CORRECTIONS,
    CLE_PIECE_CORRIGEE,
    CLE_PROPOSITION,
    CLE_RESULTAT,
    CLES_VALIDATION,
    ValeurInitiale,
    _valider_lignes,
    revenir_au_depot,
    valeur_initiale,
)
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


def test_valider_lignes_nan_ne_plante_pas():
    """Régression : une cellule vidée du data_editor vaut NaN (truthy) —
    avant le correctif, int(NaN) levait ValueError et plantait l'écran."""
    nan = float("nan")
    erreurs = _valider_lignes(
        [{"type": "aile", "longueur": nan, "angle": None, "sens": None}],
        [{"forme": "rond", "diametre": nan, "quantite": nan}],
    )
    assert any("aile" in e for e in erreurs)
    assert any("diamètre" in e for e in erreurs)
    assert any("quantité" in e for e in erreurs)


def test_valider_lignes_zero_est_invalide_mais_ne_plante_pas():
    """Régression (cas utilisateur) : 0 saisi comme longueur → erreur lisible."""
    erreurs = _valider_lignes(
        [{"type": "aile", "longueur": 0.0, "angle": None, "sens": None}], []
    )
    assert len(erreurs) == 1
    assert "aile" in erreurs[0]


def test_valider_lignes_trou_oblong_sans_dimensions():
    """Cas utilisateur : un oblong sans longueur/largeur est refusé au formulaire
    (avant : le blocage survenait plus loin, au calcul du flan)."""
    erreurs = _valider_lignes(
        [], [{"forme": "oblong", "diametre": None, "longueur": None,
              "largeur": None, "quantite": 4}]
    )
    assert len(erreurs) == 1
    assert "longueur" in erreurs[0] and "oblong" in erreurs[0]


def test_valider_lignes_trou_oblong_complet():
    erreurs = _valider_lignes(
        [], [{"forme": "oblong", "diametre": None, "longueur": 20.0,
              "largeur": 8.0, "quantite": 4}]
    )
    assert erreurs == []


def test_valider_lignes_trou_oblong_longueur_inferieure_largeur():
    erreurs = _valider_lignes(
        [], [{"forme": "oblong", "diametre": None, "longueur": 8.0,
              "largeur": 20.0, "quantite": 1}]
    )
    assert any("longueur > largeur" in e for e in erreurs)


def test_valider_lignes_trou_forme_autre_refusee():
    """« autre » a une aire indéterminable — refusé au formulaire, pas au flan."""
    erreurs = _valider_lignes(
        [], [{"forme": "autre", "diametre": 5.0, "longueur": None,
              "largeur": None, "quantite": 1}]
    )
    assert any("autre" in e for e in erreurs)


# --- Valeurs initiales des champs bornés (issue #58) -------------------------


def test_valeur_initiale_lue_dans_les_bornes():
    resultat = valeur_initiale("Épaisseur (mm)", 2.0, 0.1)
    assert resultat.valeur == 2.0
    assert resultat.origine == "plan"
    assert "lu sur le plan" in resultat.explication


def test_valeur_initiale_egale_au_minimum_acceptee():
    resultat = valeur_initiale("Largeur d'encombrement (mm)", 1.0, 1.0)
    assert resultat == ValeurInitiale(1.0, "plan", "Largeur d'encombrement (mm) : lu sur le plan.")


def test_valeur_initiale_hors_bornes_cas_umaine():
    resultat = valeur_initiale("Épaisseur (mm)", 0.06, 0.1)
    assert resultat.valeur is None
    assert resultat.origine == "hors_bornes"
    assert "Épaisseur (mm)" in resultat.explication
    assert "0,06 mm" in resultat.explication
    assert "minimum 0,1 mm" in resultat.explication


@pytest.mark.parametrize("lue", [0.0, -2.0, float("nan")])
def test_valeur_initiale_nulle_negative_nan_hors_bornes(lue):
    resultat = valeur_initiale("Largeur d'encombrement (mm)", lue, 1.0)
    assert resultat.valeur is None  # jamais remplacée par le minimum
    assert resultat.origine == "hors_bornes"
    assert "minimum 1 mm" in resultat.explication


def test_valeur_initiale_absente_sans_defaut_champ_vide():
    resultat = valeur_initiale("Épaisseur (mm)", None, 0.1)
    assert resultat.valeur is None
    assert resultat.origine == "absente"
    assert resultat.explication == "Épaisseur (mm) : non lu sur le plan, à saisir."


def test_valeur_initiale_absente_avec_defaut():
    resultat = valeur_initiale(
        "Rayon de pliage général (mm)",
        None,
        0.1,
        defaut=(2.0, "paramètre rayon_pliage_defaut_mm"),
    )
    assert resultat.valeur == 2.0
    assert resultat.origine == "defaut"
    assert "2 mm" in resultat.explication
    assert "rayon_pliage_defaut_mm" in resultat.explication
    assert "à confirmer" in resultat.explication


def test_valeur_initiale_defaut_hors_bornes():
    resultat = valeur_initiale(
        "Rayon de pliage général (mm)",
        None,
        0.1,
        defaut=(0.05, "paramètre rayon_pliage_defaut_mm"),
    )
    assert resultat.valeur is None
    assert resultat.origine == "hors_bornes"
    assert "0,05 mm" in resultat.explication
    assert "minimum 0,1 mm" in resultat.explication
    assert "rayon_pliage_defaut_mm" in resultat.explication


def test_valeur_initiale_lue_prioritaire_sur_defaut():
    resultat = valeur_initiale("Rayon de pliage général (mm)", 3.0, 0.1, defaut=(2.0, "paramètre"))
    assert (resultat.valeur, resultat.origine) == (3.0, "plan")


def test_valeur_initiale_lue_hors_bornes_ne_retombe_pas_sur_defaut():
    """Une lecture aberrante est signalée, pas masquée par le défaut."""
    resultat = valeur_initiale("Rayon de pliage général (mm)", 0.0, 0.1, defaut=(2.0, "paramètre"))
    assert (resultat.valeur, resultat.origine) == (None, "hors_bornes")


# --- Retour au dépôt (issue #58) ---------------------------------------------


def test_revenir_au_depot_purge_l_etat_de_validation():
    etat = {cle: "x" for cle in CLES_VALIDATION}
    etat[CLE_CONTEXTE] = {"client_id": "C1"}
    etat["autre"] = 1
    revenir_au_depot(etat)
    assert etat == {CLE_CONTEXTE: {"client_id": "C1"}, "autre": 1}


def test_revenir_au_depot_cles_absentes_sans_erreur():
    etat = {CLE_RESULTAT: "r"}
    revenir_au_depot(etat)
    assert etat == {}


def test_cles_validation_couvrent_etat_et_editeurs():
    assert set(CLES_VALIDATION) == {
        CLE_RESULTAT,
        CLE_PIECE_CORRIGEE,
        CLE_PROPOSITION,
        CLE_CORRECTIONS,
        "texte_en_cours",
        "texte_correction",
        "editeur_profil",
        "editeur_trous",
    }
