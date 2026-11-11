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
    calculer_bloc_composants,
    calculer_bloc_decoupe,
    calculer_bloc_finition,
    calculer_bloc_matiere,
    calculer_bloc_pliage,
    calculer_bloc_soudure,
    calculer_blocs_1_3,
    calculer_blocs_4_6,
    chiffrer,
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
    Soudure,
    Trou,
    TypeTraitement,
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


# ---------------------------------------------------------------------------
# Blocs 4 à 6 (issue #14)
# ---------------------------------------------------------------------------


def test_bloc_soudure_piece_sans_soudure():
    """Pièce unique découpée-pliée : bloc 4 à zéro."""
    bloc = calculer_bloc_soudure(piece_003())
    assert bloc.cout_variable_eur == 0.0
    assert bloc.cout_fixe_eur_par_lot == 0.0


def test_bloc_soudure_piece_soudee_erreur():
    """Une pièce soudée est refusée explicitement (hors périmètre V1)."""
    piece = piece_003()
    piece.soudures.append(Soudure(procede="mig_mag", longueur=30.0))
    with pytest.raises(ErreurChiffrage, match="soudé hors périmètre V1"):
        calculer_bloc_soudure(piece)


def test_bloc_finition_non_specifiee_absente(session, flan_003):
    """Traitement non spécifié sur le plan → exclu du chiffrage de base."""
    assert calculer_bloc_finition(piece_003(), flan_003, session) is None


def test_bloc_finition_option_peinture_piece_003(session, flan_003):
    """§8.3 : option peinture poudre ≈ 0,27 €/pièce, minimum de lot 80 €
    → contribution à Q=100 = max(0,27 ; 80 ÷ 100) = 0,80 €/pièce."""
    bloc = calculer_bloc_finition(piece_003(), flan_003, session, traitement_id="PEINTURE_POUDRE")
    assert bloc is not None
    assert bloc.surface_traitee_m2 == pytest.approx(2 * flan_003.surface_nette_mm2 * 1e-6)
    assert bloc.cout_variable_eur == pytest.approx(0.27, abs=0.02)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(80.0)
    assert max(bloc.cout_variable_eur, bloc.cout_fixe_eur_par_lot / QUANTITE) == pytest.approx(
        0.80, abs=0.02
    )


def test_bloc_finition_type_du_plan_resolu(session, flan_003):
    """Un type de traitement extrait du plan est résolu via le référentiel."""
    piece = piece_003()
    piece.traitement.type = Champ[TypeTraitement](valeur="thermolaquage")
    bloc = calculer_bloc_finition(piece, flan_003, session)
    assert bloc is not None
    assert bloc.traitement_id == "PEINTURE_POUDRE"


def test_bloc_finition_tarif_kg_hors_perimetre(session, flan_003):
    """Un traitement tarifé au kg (galvanisation) est refusé explicitement."""
    with pytest.raises(ErreurChiffrage, match="tarifé au kg"):
        calculer_bloc_finition(piece_003(), flan_003, session, traitement_id="GALVA_CHAUD")


def test_bloc_finition_traitement_inconnu(session, flan_003):
    with pytest.raises(ErreurChiffrage, match="Traitement inconnu"):
        calculer_bloc_finition(piece_003(), flan_003, session, traitement_id="INCONNU")


def test_bloc_composants_piece_003(session):
    """§8.3 : écrous 2 × 0,20 = 0,40 € ; sertissage 24 s + ébavurage 10 s
    = 34 s × 50 €/h ≈ 0,47 € ; réglage sertisseuse 10 min × 50 €/h ≈ 8,3 €
    de fixe/lot → bloc 6 ≈ 0,95 €/pièce à Q=100."""
    bloc = calculer_bloc_composants(piece_003(), [("ES-M6-A", 2)], session)
    assert bloc.cout_composants_eur == pytest.approx(0.40)
    assert bloc.temps_operations_s == pytest.approx(34.0)  # 2 × 12 + 10
    assert bloc.cout_operations_eur == pytest.approx(0.47, abs=0.01)
    assert bloc.cout_variable_eur == pytest.approx(0.87, abs=0.01)
    assert bloc.cout_fixe_eur_par_lot == pytest.approx(50.0 / 6.0, rel=0.01)
    assert bloc.postes_utilises == ["MANUEL", "SERTISSEUSE"]
    assert bloc.cout_variable_eur + bloc.cout_fixe_eur_par_lot / QUANTITE == pytest.approx(
        0.95, abs=0.02
    )


def test_bloc_composants_piece_sans_composant(session):
    """Pièce sans composant ni trou fileté : bloc 6 à zéro, sans ébavurage."""
    bloc = calculer_bloc_composants(piece_003(), [], session)
    assert bloc.cout_variable_eur == 0.0
    assert bloc.cout_fixe_eur_par_lot == 0.0
    assert bloc.postes_utilises == []


def test_bloc_composants_taraudage(session):
    """Un trou fileté ajoute un taraudage (et l'ébavurage)."""
    piece = piece_003()
    piece.contours.trous[0].filetage = "M8"
    bloc = calculer_bloc_composants(piece, [], session)
    # taraudage × 2 (quantité du trou) + ébavurage × 1, poste MANUEL (réglage 0)
    assert bloc.temps_operations_s == pytest.approx(2 * 20.0 + 10.0)
    assert bloc.postes_utilises == ["MANUEL"]
    assert bloc.cout_fixe_eur_par_lot == 0.0


def test_bloc_composants_reference_inconnue(session):
    with pytest.raises(ErreurChiffrage, match="Composant inconnu"):
        calculer_bloc_composants(piece_003(), [("INCONNU", 1)], session)


def test_calculer_blocs_4_6_piece_003(session, flan_003):
    """Pièce de référence : soudure 0, finition absente, bloc 6 ≈ 0,95 € à Q=100."""
    blocs = calculer_blocs_4_6(piece_003(), flan_003, session, composants=[("ES-M6-A", 2)])
    assert blocs.soudure.cout_variable_eur == 0.0
    assert blocs.finition is None
    assert blocs.composants.cout_variable_eur + (
        blocs.composants.cout_fixe_eur_par_lot / QUANTITE
    ) == pytest.approx(0.95, abs=0.02)


# ---------------------------------------------------------------------------
# Agrégation (issue #15) : chiffrer()
# ---------------------------------------------------------------------------


def _palier(chiffrage, q):
    return next(p for p in chiffrage.paliers if p.quantite == q)


def test_chiffrer_piece_003_q100(session):
    """§8.3 : coût ≈ 2,20 € et prix ≈ 2,93 € à Q=100, recalculés depuis les
    tables seedées (blocs 0,10 / 0,60 / 0,54 / 0 / 0 / 0,95)."""
    result = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)])
    p = _palier(result, 100)
    assert p.cout_unitaire_eur == pytest.approx(2.20, abs=0.03)
    assert p.prix_unitaire_eur == pytest.approx(2.93, abs=0.05)


def test_chiffrer_piece_003_paliers(session):
    """§8.4 : coûts unitaires 63,25 / 7,75 / 1,65 € aux paliers 1 / 10 / 1000."""
    result = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)])
    assert _palier(result, 1).cout_unitaire_eur == pytest.approx(63.25, abs=0.3)
    assert _palier(result, 10).cout_unitaire_eur == pytest.approx(7.75, abs=0.1)
    assert _palier(result, 1000).cout_unitaire_eur == pytest.approx(1.65, abs=0.05)
    # §8.4 : prix unitaires correspondants (marge 25 %)
    assert _palier(result, 1).prix_unitaire_eur == pytest.approx(84.33, abs=0.5)
    assert _palier(result, 1000).prix_unitaire_eur == pytest.approx(2.19, abs=0.05)


def test_chiffrer_paliers_defaut_depuis_base(session):
    """Sans argument, les paliers viennent du paramètre paliers_quantite."""
    result = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)])
    assert [p.quantite for p in result.paliers] == [1, 10, 100, 1000]


def test_chiffrer_paliers_explicites(session):
    result = chiffrer(piece_003(), MATIERE, session, quantites=[25], composants=[])
    assert [p.quantite for p in result.paliers] == [25]


def test_chiffrer_quantite_invalide(session):
    with pytest.raises(ErreurChiffrage, match="Paliers de quantité invalides"):
        chiffrer(piece_003(), MATIERE, session, quantites=[100, 0])


def test_chiffrer_marge_client(session):
    """CLI001 a une marge spécifique de 18 % : prix = coût ÷ 0,82."""
    result = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)], client_id="CLI001")
    p = _palier(result, 100)
    assert p.prix_unitaire_eur == pytest.approx(p.cout_unitaire_eur / 0.82, rel=1e-9)
    assert p.prix_unitaire_eur == pytest.approx(2.20 / 0.82, abs=0.05)


def test_chiffrer_client_inconnu(session):
    with pytest.raises(ErreurChiffrage, match="Client inconnu"):
        chiffrer(piece_003(), MATIERE, session, client_id="INCONNU")


def test_chiffrer_matiere_inconnue(session):
    with pytest.raises(ErreurChiffrage, match="Matière inconnue"):
        chiffrer(piece_003(), "INCONNU", session)


def test_chiffrer_faisabilite_bloquante(session):
    """Épaisseur non disponible pour la matière → blocage → pas de chiffrage."""
    piece = piece_003()
    piece.matiere.epaisseur = Champ[float](valeur=7.0)  # non dispo pour S235JR
    with pytest.raises(ErreurChiffrage, match="faisabilité bloquante"):
        chiffrer(piece, MATIERE, session)


def test_chiffrer_trace_complete(session):
    """Chaque bloc a sa ligne de trace (formule, valeurs, table, date du prix)."""
    result = chiffrer(piece_003(), MATIERE, session, composants=[("ES-M6-A", 2)])
    blocs = {ligne.bloc for ligne in result.trace}
    assert blocs == {"matiere", "decoupe", "pliage", "soudure", "composants", "marge"}
    for ligne in result.trace:
        assert ligne.formule
        assert ligne.table_origine
    matiere_ligne = next(ligne for ligne in result.trace if ligne.bloc == "matiere")
    assert matiere_ligne.table_origine == "matieres"
    assert matiere_ligne.date_prix == get_matiere(MATIERE, session).date_maj
    marge_ligne = next(ligne for ligne in result.trace if ligne.bloc == "marge")
    assert marge_ligne.valeurs["marge"] == pytest.approx(0.25)
    # Figeable : le résultat est sérialisable tel quel
    assert result.model_dump_json()


def test_chiffrer_piece_avec_traitement(session):
    """Une pièce avec traitement spécifié inclut la finition (max avec min de lot)."""
    piece = piece_003()
    piece.traitement.type = Champ[TypeTraitement](valeur="thermolaquage")
    result = chiffrer(piece, MATIERE, session, composants=[("ES-M6-A", 2)])
    p = _palier(result, 100)
    assert p.cout_unitaire_eur == pytest.approx(2.20 + 0.80, abs=0.06)
    assert any(ligne.bloc == "finition" for ligne in result.trace)
