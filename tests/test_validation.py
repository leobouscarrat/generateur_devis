"""Tests de l'écran de validation : rechiffrer et rendu 3D (issue #24).

Fonctions pures uniquement (pas de Streamlit) : ``rechiffrer`` enchaîne
géométrie → faisabilité → chiffrage → contrôles sur une pièce modifiée, et
``maillage_vers_figure`` convertit le maillage en figure plotly.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.acces import list_composants
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.modele3d import construire_modele_3d
from generateur_devis.schema.piece import (
    Aile,
    Anomalie,
    Champ,
    CoinCoupe,
    Composant,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
    Unite,
)
from generateur_devis.ui.app import (
    CLE_CONTEXTE,
    CLE_CORRECTIONS,
    CLE_PIECE_CORRIGEE,
    CLE_PROPOSITION,
    CLE_RESULTAT,
    CLES_VALIDATION,
    LIBELLES_ANOMALIE,
    LectureComposants,
    MatiereInitiale,
    Rattachement,
    ValeurInitiale,
    _champs_peu_surs,
    _editer_piece,
    _ligne_remplie,
    _valider_lignes,
    libelle_composant,
    lignes_anomalies,
    lire_composants,
    matiere_initiale,
    proposer_rattachement,
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
        {"type": "aile", "longueur": 18.0, "angle": None, "sens": None},
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
        [
            {"type": "aile", "longueur": 30.0, "angle": None, "sens": None},
            {"type": "pli", "longueur": None, "angle": None, "sens": "gauche"},
            {"type": "aile", "longueur": 20.0, "angle": None, "sens": None},
        ],
        [],
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


# --- Profil : bornes d'angle, alternance, lignes vides (issue #65) ------------

NAN = float("nan")


def _aile(longueur: float) -> dict:
    return {"type": "aile", "longueur": longueur, "angle": None, "sens": None}


def _pli(angle: float, sens: str = "haut") -> dict:
    return {"type": "pli", "longueur": None, "angle": angle, "sens": sens}


@pytest.mark.parametrize("angle", [0.0, -5.0, 180.01, 200.0])
def test_valider_lignes_angle_hors_bornes(angle):
    erreurs = _valider_lignes([_aile(30.0), _pli(angle), _aile(20.0)], [])
    assert len(erreurs) == 1
    assert "Profil ligne 2" in erreurs[0]
    assert "entre 0 et 180" in erreurs[0]


@pytest.mark.parametrize("angle", [180.0, 0.5])
def test_valider_lignes_angle_dans_les_bornes(angle):
    assert _valider_lignes([_aile(30.0), _pli(angle), _aile(20.0)], []) == []


@pytest.mark.parametrize("angle", [0.0, -5.0, 0.5, 90.0, 180.0, 180.01, 200.0])
def test_bornes_angle_formulaire_egales_bornes_schema(angle):
    """Garde-fou : _valider_lignes accepte exactement les angles acceptés par Pli."""
    accepte_formulaire = _valider_lignes([_aile(30.0), _pli(angle), _aile(20.0)], []) == []
    try:
        Pli(angle=angle, sens="haut")
        accepte_schema = True
    except ValidationError:
        accepte_schema = False
    assert accepte_formulaire == accepte_schema


def test_valider_lignes_angle_nan_un_seul_message():
    """Cellule d'angle vidée → « pli sans angle », pas de 2e message de bornes."""
    erreurs = _valider_lignes([_aile(30.0), _pli(NAN), _aile(20.0)], [])
    assert erreurs == ["Profil ligne 2 : pli sans angle."]


def test_valider_lignes_alternance_ligne_supprimee():
    """aile, aile, pli, aile (un pli supprimé) → une seule erreur, sur la ligne 2."""
    erreurs = _valider_lignes([_aile(42.0), _aile(22.0), _pli(90.0), _aile(18.0)], [])
    assert len(erreurs) == 1
    assert "Profil ligne 2" in erreurs[0]
    assert "pli attendu" in erreurs[0]
    assert "alternent" in erreurs[0]


def test_valider_lignes_profil_finit_par_un_pli():
    erreurs = _valider_lignes([_aile(42.0), _pli(90.0)], [])
    assert erreurs == ["Profil : le profil doit finir par une aile."]


def test_valider_lignes_profil_commence_par_un_pli():
    erreurs = _valider_lignes([_pli(90.0), _aile(42.0)], [])
    assert len(erreurs) == 1
    assert "Profil ligne 1" in erreurs[0]
    assert "aile attendu" in erreurs[0]


def test_valider_lignes_type_invalide_exclu_de_l_alternance():
    """Une ligne de type invalide ne déclenche pas d'erreur d'alternance en cascade."""
    erreurs = _valider_lignes(
        [_aile(42.0), _pli(90.0), {"type": "courbe", "longueur": 5.0}, _aile(18.0)], []
    )
    assert len(erreurs) == 1
    assert "Profil ligne 3" in erreurs[0] and "type" in erreurs[0]


def test_valider_lignes_ligne_vide_intercalee_ignoree():
    vide = {"type": None, "longueur": NAN, "angle": NAN, "sens": None}
    assert _valider_lignes([_aile(42.0), vide, _pli(90.0), _aile(18.0)], []) == []


def test_valider_lignes_piece_plate_valide():
    assert _valider_lignes([_aile(75.0)], []) == []


def test_valider_lignes_ligne_neuve_nan_ignoree():
    """Ligne neuve du data_editor : cellules numériques NaN → ni erreur ni élément."""
    erreurs = _valider_lignes(
        [{"type": None, "longueur": NAN, "angle": NAN, "sens": None}],
        [{"forme": None, "diametre": NAN, "longueur": NAN, "largeur": NAN, "quantite": NAN}],
    )
    assert erreurs == []


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ({"a": None, "b": ""}, False),
        ({"a": NAN, "b": None}, False),
        ({}, False),
        ({"a": 0.0, "b": None}, True),
        ({"a": None, "b": "aile"}, True),
    ],
)
def test_ligne_remplie(ligne, attendu):
    assert _ligne_remplie(ligne) is attendu


def _faux_data_editor(profil: pd.DataFrame | None, trous: pd.DataFrame | None):
    """Remplace st.data_editor : renvoie le tableau « édité » selon la clé."""

    def data_editor(donnees, *, key, **_):
        remplacement = {"editeur_profil": profil, "editeur_trous": trous}[key]
        return donnees if remplacement is None else remplacement

    return data_editor


def _editer(piece: PieceExtraite):
    choix = {"S235JR — acier (EN 10025)": "S235JR"}
    matiere = matiere_initiale(None, piece.matiere.designation.valeur, choix.values())
    return _editer_piece(piece, choix, matiere)


def test_editer_piece_profil_vide_donne_profil_none(monkeypatch):
    """Toutes les lignes du profil supprimées → profil None, pas le profil extrait."""
    vide = pd.DataFrame([], columns=["type", "longueur", "angle", "sens"])
    monkeypatch.setattr("generateur_devis.ui.app.st.data_editor", _faux_data_editor(vide, None))
    editee, _, erreurs = _editer(piece_support(MATIERE))
    assert erreurs == []
    assert editee is not None
    assert editee.profil_pliage is None


def test_editer_piece_ligne_neuve_nan_sans_trou_fantome(monkeypatch):
    """Ligne neuve vide (NaN) dans les trous et le profil : aucun élément créé."""
    profil = pd.DataFrame(
        [_aile(75.0), {"type": None, "longueur": NAN, "angle": NAN, "sens": None}],
        columns=["type", "longueur", "angle", "sens"],
    )
    trous = pd.DataFrame(
        [
            {"forme": "rond", "diametre": 8.0, "longueur": NAN, "largeur": NAN, "quantite": 2},
            {"forme": None, "diametre": NAN, "longueur": NAN, "largeur": NAN, "quantite": NAN},
        ],
        columns=["forme", "diametre", "longueur", "largeur", "quantite"],
    )
    monkeypatch.setattr(
        "generateur_devis.ui.app.st.data_editor", _faux_data_editor(profil, trous)
    )
    editee, _, erreurs = _editer(piece_support(MATIERE))
    assert erreurs == []
    assert editee is not None
    assert [(t.forme, t.diametre, t.quantite) for t in editee.contours.trous] == [
        ("rond", 8.0, 2)
    ]
    assert editee.profil_pliage is not None
    assert len(editee.profil_pliage.elements) == 1


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
        "editeur_composants",
    }


# --- Matière pré-sélectionnée (issue #55) ------------------------------------

# 304L en premier : piège un repli sur l'index 0 de la liste.
IDS_MATIERES = ["304L", "316L", "S235JR"]


def test_matiere_initiale_depot_sans_designation():
    m = matiere_initiale("S235JR", None, IDS_MATIERES)
    assert (m.matiere_id, m.origine, m.alerte) == ("S235JR", "depot", None)
    assert m.explication == "Matière : choisie au dépôt (absente du plan)."


def test_matiere_initiale_depot_identique_au_plan():
    m = matiere_initiale("S235JR", "S235JR", IDS_MATIERES)
    assert (m.matiere_id, m.origine, m.alerte) == ("S235JR", "depot", None)
    assert m.explication == "Matière : choisie au dépôt, identique au plan."


def test_matiere_initiale_conflit_depot_plan_alerte():
    m = matiere_initiale("S235JR", "304L", IDS_MATIERES)
    assert (m.matiere_id, m.origine) == ("S235JR", "depot")
    assert m.explication == "Matière : choisie au dépôt."
    assert m.alerte == "⚠️ Matière : choix du dépôt S235JR retenu, le plan indique « 304L »."


def test_matiere_initiale_conflit_depot_correction_assistant():
    m = matiere_initiale("S235JR", "316L", IDS_MATIERES, corrigee=True)
    assert m.matiere_id == "S235JR"
    assert m.alerte == (
        "⚠️ Matière : choix du dépôt S235JR retenu, la correction de l'assistant indique « 316L »."
    )


def test_matiere_initiale_plan_connu():
    m = matiere_initiale(None, "S235JR", IDS_MATIERES)
    assert (m.matiere_id, m.origine, m.alerte) == ("S235JR", "plan", None)
    assert m.explication == "Matière : lue sur le plan."


def test_matiere_initiale_corrigee_par_assistant():
    m = matiere_initiale(None, "S235JR", IDS_MATIERES, corrigee=True)
    assert (m.matiere_id, m.origine) == ("S235JR", "assistant")
    assert m.explication == "Matière : corrigée par l'assistant."


def test_matiere_initiale_designation_inconnue_aucune_preselection():
    m = matiere_initiale(None, "16 GAUGE A36 STEEL", IDS_MATIERES)
    assert (m.matiere_id, m.origine) == (None, "inconnue")
    assert m.explication == (
        "Matière : « 16 GAUGE A36 STEEL » lue sur le plan, inconnue du référentiel : à choisir."
    )


def test_matiere_initiale_casse_differente_inconnue():
    m = matiere_initiale(None, "s235jr", IDS_MATIERES)
    assert (m.matiere_id, m.origine) == (None, "inconnue")


@pytest.mark.parametrize("designation", [None, "", "  "])
def test_matiere_initiale_absente(designation):
    m = matiere_initiale(None, designation, IDS_MATIERES)
    assert (m.matiere_id, m.origine) == (None, "absente")
    assert m.explication == "Matière : absente du plan et non choisie au dépôt : à choisir."


def test_matiere_initiale_designation_avec_espaces_reconnue():
    m = matiere_initiale(None, " S235JR ", IDS_MATIERES)
    assert (m.matiere_id, m.origine) == ("S235JR", "plan")


def test_matiere_initiale_depot_inconnu_ignore():
    m = matiere_initiale("X", "S235JR", IDS_MATIERES)
    assert (m.matiere_id, m.origine, m.alerte) == ("S235JR", "plan", None)
    assert m.explication.startswith("Choix du dépôt « X » inconnu du référentiel ; ")
    assert m.explication.endswith("Matière : lue sur le plan.")


def test_matiere_initiale_depot_inconnu_sans_designation():
    m = matiere_initiale("X", None, IDS_MATIERES)
    assert (m.matiere_id, m.origine) == (None, "absente")
    assert "« X »" in m.explication


@pytest.mark.parametrize(
    ("depot", "designation", "corrigee"),
    [
        ("S235JR", None, False),
        ("S235JR", "304L", False),
        ("S235JR", "S235JR", False),
        (None, "S235JR", False),
        (None, "S235JR", True),
        (None, "16 GAUGE A36 STEEL", False),
        (None, None, False),
        (None, "", False),
        (None, "  ", False),
        ("X", "S235JR", False),
        ("X", None, False),
        ("316L", "inconnue", True),
    ],
)
def test_matiere_initiale_invariants(depot, designation, corrigee):
    m = matiere_initiale(depot, designation, IDS_MATIERES, corrigee=corrigee)
    assert isinstance(m, MatiereInitiale)
    assert m.explication.strip()
    assert m.matiere_id is None or m.matiere_id in IDS_MATIERES
    if "304L" not in (depot, designation):
        assert m.matiere_id != "304L"


# --- Plans en pouces : origine convertie (issue #57) --------------------------


def test_valeur_initiale_lue_sur_plan_en_pouces():
    resultat = valeur_initiale("Épaisseur (mm)", 1.524, 0.1, lue_sur_plan="0,06 in")
    assert resultat == ValeurInitiale(
        1.524, "plan", "Épaisseur (mm) : lu sur le plan : 0,06 in → 1,52 mm."
    )


def test_valeur_initiale_hors_bornes_en_pouces():
    """0,002 in = 0,0508 mm < 0,1 mm : signalé avec la lecture d'origine."""
    resultat = valeur_initiale("Épaisseur (mm)", 0.0508, 0.1, lue_sur_plan="0,002 in")
    assert resultat.valeur is None
    assert resultat.origine == "hors_bornes"
    assert resultat.explication == (
        "Épaisseur (mm) : valeur lue hors bornes : 0,002 in → 0,05 mm (minimum 0,1 mm), à saisir."
    )


def test_valeur_initiale_sans_lue_sur_plan_inchangee():
    """Rétrocompatible : sans lecture en pouces, l'explication de #58 est inchangée."""
    assert valeur_initiale("Épaisseur (mm)", 1.524, 0.1).explication == (
        "Épaisseur (mm) : lu sur le plan."
    )


def test_champs_peu_surs_inclut_unite_du_plan(session):
    """Unité lue avec une confiance sous seuil_confiance_champs (0,7 au seed)."""
    piece = piece_support(MATIERE)
    piece.unites = Champ[Unite](valeur="in", confiance=0.4)
    assert "unité du plan : confiance 40%" in _champs_peu_surs(piece, session)
    piece.unites = Champ[Unite](valeur="in", confiance=0.9)
    assert not [c for c in _champs_peu_surs(piece, session) if c.startswith("unité du plan")]


# --- Composants rattachés au référentiel (issue #56) --------------------------


@pytest.fixture
def referentiel(session):
    return list_composants(session)


def _ref(referentiel, reference):
    return next(c for c in referentiel if c.reference == reference)


@pytest.mark.parametrize(
    ("type_", "filetage", "attendue"),
    [
        ("ecrou_a_sertir", "M4", "ES-M4-A"),
        ("ecrou_a_sertir", "M8", "ES-M8-A"),
        ("goujon_a_sertir", "M6", "GS-M6-A"),
        ("entretoise_a_sertir", "M4", "ENT-M4-10"),
    ],
)
def test_proposer_rattachement_candidat_unique(referentiel, type_, filetage, attendue):
    composant = Composant(designation="x", type=type_, filetage=filetage, quantite=2)
    rattachement = proposer_rattachement(composant, referentiel)
    assert rattachement.reference == attendue
    assert "à confirmer" in rattachement.explication


def test_proposer_rattachement_explication_candidat_unique(referentiel):
    composant = Composant(designation="x", type="ecrou_a_sertir", filetage="M4")
    assert proposer_rattachement(composant, referentiel) == Rattachement(
        "ES-M4-A", "Seule référence ecrou_sertir M4 du référentiel : à confirmer."
    )


def test_proposer_rattachement_plusieurs_candidats_aucune_preselection(referentiel):
    """Écrou M6 : ES-M6-A, ES-M6-B (lot), ES-M6-X (inox) → l'utilisateur choisit."""
    composant = Composant(designation="Écrou M6", type="ecrou_a_sertir", filetage="M6")
    assert proposer_rattachement(composant, referentiel) == Rattachement(
        None, "3 références possibles (ES-M6-A, ES-M6-B, ES-M6-X) : à choisir."
    )


@pytest.mark.parametrize(
    ("type_", "filetage"),
    [
        ("rivet", "M4"),
        ("insert", "M6"),
        ("autre", "M6"),
        ("ecrou_a_sertir", None),
        ("ecrou_a_sertir", "M12"),
    ],
)
def test_proposer_rattachement_aucune_correspondance(referentiel, type_, filetage):
    composant = Composant(designation="x", type=type_, filetage=filetage)
    assert proposer_rattachement(composant, referentiel) == Rattachement(
        None,
        "Aucune référence correspondante au référentiel : à choisir ou à ajouter (admin).",
    )


def test_libelle_composant(referentiel):
    assert libelle_composant(_ref(referentiel, "ES-M6-A")) == (
        "ES-M6-A — Écrou à sertir M6 (0,20 €/u)"
    )
    assert libelle_composant(_ref(referentiel, "ES-M6-B")) == (
        "ES-M6-B — Écrou à sertir M6 (lot 1000) (0,15 €/u, lot ≥ 1000)"
    )


ECROU_M6 = Composant(designation="Écrou M6", type="ecrou_a_sertir", filetage="M6", quantite=2)
LIBELLE_A = "ES-M6-A — Écrou à sertir M6 (0,20 €/u)"
PAR_LIBELLE = {LIBELLE_A: "ES-M6-A"}


def _ligne(quantite, reference):
    return {
        "composant": "Écrou M6",
        "type": "ecrou_a_sertir",
        "filetage": "M6",
        "quantite": quantite,
        "reference": reference,
        "origine": "…",
    }


def test_lire_composants_reference_choisie():
    lecture = lire_composants([ECROU_M6], [_ligne(2, LIBELLE_A)], PAR_LIBELLE)
    assert lecture.a_chiffrer == [("ES-M6-A", 2)]
    assert lecture.non_chiffres == []
    assert lecture.erreurs == []
    assert lecture.nomenclature == [ECROU_M6]


@pytest.mark.parametrize("vide", [None, "", float("nan")])
def test_lire_composants_reference_vide_non_chiffre(vide):
    lecture = lire_composants([ECROU_M6], [_ligne(2, vide)], PAR_LIBELLE)
    assert lecture.a_chiffrer == []
    assert lecture.erreurs == []
    assert len(lecture.non_chiffres) == 1
    assert "Écrou M6 × 2" in lecture.non_chiffres[0]
    assert lecture.non_chiffres[0].startswith("Composant non chiffré")


def test_lire_composants_quantite_modifiee():
    lecture = lire_composants([ECROU_M6], [_ligne(3.0, LIBELLE_A)], PAR_LIBELLE)
    assert lecture.nomenclature[0].quantite == 3
    assert lecture.nomenclature[0].designation == "Écrou M6"
    assert lecture.a_chiffrer == [("ES-M6-A", 3)]
    assert ECROU_M6.quantite == 2  # entrée non mutée


@pytest.mark.parametrize("quantite", [float("nan"), None, 0, -1, 2.5])
def test_lire_composants_quantite_invalide_bloquante(quantite):
    lecture = lire_composants([ECROU_M6], [_ligne(quantite, LIBELLE_A)], PAR_LIBELLE)
    assert len(lecture.erreurs) == 1
    assert "Écrou M6" in lecture.erreurs[0]
    assert lecture.a_chiffrer == []


def test_lire_composants_meme_reference_deux_lignes():
    autre = Composant(designation="Écrou M6 bis", type="ecrou_a_sertir", filetage="M6")
    lecture = lire_composants(
        [ECROU_M6, autre], [_ligne(2, LIBELLE_A), _ligne(1, LIBELLE_A)], PAR_LIBELLE
    )
    assert lecture.a_chiffrer == [("ES-M6-A", 2), ("ES-M6-A", 1)]


def test_lire_composants_vide():
    lecture = lire_composants([], [], {})
    assert lecture == LectureComposants([], [], [], [])


# --- Anomalies signalées par l'IA (issue #64) ------------------------------------


def test_lignes_anomalies_libelle_et_ordre():
    piece = piece_support(MATIERE)
    piece.anomalies = [
        Anomalie(
            type="information_manquante",
            champ="matiere.designation",
            description="matière non indiquée sur le plan",
        ),
        Anomalie(type="incoherence", champ=None, description="cotes contradictoires"),
    ]
    assert lignes_anomalies(piece) == [
        "Information manquante : matière non indiquée sur le plan",
        "Incohérence : cotes contradictoires",
    ]


def test_lignes_anomalies_aucune():
    assert lignes_anomalies(piece_support(MATIERE)) == []


def test_libelles_anomalie_couvrent_le_schema():
    """Garde-fou : tout type d'anomalie du schéma a un libellé, et rien de plus."""
    from typing import get_args

    types = set(get_args(Anomalie.model_fields["type"].annotation))
    assert types == {"information_manquante", "incoherence", "illisible", "autre"}
    assert set(LIBELLES_ANOMALIE) == types
