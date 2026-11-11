"""Tests des contrôles de cohérence du chiffrage (issue #16).

Base SQLite en mémoire seedée. Les bornes viennent de la table
``bornes_controle`` seedée : prix au kg [2, 150] €/kg (masse ≤ 1 kg),
part matière [3, 70] % (Q ≥ 100), écart historique [−30, +30] %.
piece_support (71 g, 41 €/kg, part matière ≈ 4,4 %) ne doit déclencher aucune
de ces trois alertes (§8.5).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.calcul_prix import chiffrer
from generateur_devis.controles_prix import evaluer_controles_prix
from generateur_devis.data.acces import get_matiere, get_parametre
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, BorneControle, HistoriqueDevis, Matiere
from generateur_devis.geometrie import construire_flan
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Contours,
    Encombrement,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.schema.piece import (
    Matiere as MatierePiece,
)

MATIERE = "S235JR"
FACTEUR_K = 0.40


def piece_support() -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures."""
    return PieceExtraite(
        matiere=MatierePiece(epaisseur=Champ[float](valeur=2.0)),
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
def chiffrage_003(session):
    return chiffrer(piece_support(), MATIERE, session, composants=[("ES-M6-A", 2)])


@pytest.fixture
def flan_003(session):
    matiere = get_matiere(MATIERE, session)
    return construire_flan(piece_support(), matiere.densite_kg_dm3, FACTEUR_K)


def _regles(constats):
    return {c.regle for c in constats}


def test_piece_support_sans_alerte_prix(session, chiffrage_003, flan_003):
    """§8.5 : 41 €/kg et part matière ≈ 4,4 % sont normaux pour cette pièce ;
    le prix matière seedé est récent. Alertes seulement, jamais de blocage."""
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_003, MATIERE, session)
    assert "prix_au_kg" not in _regles(constats)
    assert "part_matiere" not in _regles(constats)
    assert "prix_matiere_ancien" not in _regles(constats)
    assert all(c.severite == "alerte" for c in constats)


def test_alerte_prix_au_kg(session, chiffrage_003, flan_003):
    """Même chiffrage mais masse nette quasi nulle → prix/kg au-delà du max."""
    flan_min = flan_003.model_copy(update={"masse_nette_kg": 0.01})
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_min, MATIERE, session)
    assert "prix_au_kg" in _regles(constats)


def test_alerte_part_matiere(session, chiffrage_003, flan_003):
    """Un coût matière artificiellement dominant déclenche l'alerte."""
    chiffrage_003.blocs_1_3.matiere.cout_variable_eur = 10.0  # part ≈ 80 %
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_003, MATIERE, session)
    assert "part_matiere" in _regles(constats)


def test_alerte_prix_matiere_ancien(session, flan_003):
    """Un prix matière plus vieux que le paramètre déclenche l'alerte."""
    max_age = int(get_parametre("prix_matiere_max_age_jours", session))
    vieille = date.today() - timedelta(days=max_age + 30)
    session.merge(
        Matiere(
            id=MATIERE, famille="acier", densite_kg_dm3=7.85, prix_eur_kg=1.10, date_maj=vieille
        )
    )
    session.flush()
    chiffrage = chiffrer(piece_support(), MATIERE, session, composants=[("ES-M6-A", 2)])
    constats = evaluer_controles_prix(chiffrage, piece_support(), flan_003, MATIERE, session)
    assert "prix_matiere_ancien" in _regles(constats)


def _devis_similaire(indice: int, cout: float) -> HistoriqueDevis:
    return HistoriqueDevis(
        id=f"D-TEST-{indice:04d}",
        date=date.today(),
        client_id=None,
        reference_piece="Support test",
        designation="Support test",
        matiere_id=MATIERE,
        epaisseur_mm=2.0,
        flan_l_mm=75.0,
        flan_w_mm=60.0,
        masse_kg=0.07,
        longueur_coupe_mm=343.0,
        nb_trous=4,
        nb_plis=2,
        nb_composants=2,
        traitement_id=None,
        quantite=100,
        cout_unitaire_eur=cout,
        prix_unitaire_eur=cout * 1.3,
        statut="accepte",
    )


def test_alerte_ecart_historique(session, chiffrage_003, flan_003):
    """Assez de devis similaires très chers dans l'historique déclenche l'écart."""
    for i in range(3):
        session.add(_devis_similaire(i + 1, 10.0))  # ~4,5× le coût → écart > 30 %
    session.flush()
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_003, MATIERE, session)
    assert "ecart_historique" in _regles(constats)


def test_ecart_historique_echantillon_trop_petit(session, chiffrage_003, flan_003):
    """1-2 devis similaires seulement → pas d'alerte : une « moyenne » sur un
    échantillon pareil ne veut rien dire (paramètre min_echantillon = 3)."""
    session.query(HistoriqueDevis).delete()  # on isole du seed simulé
    for i in range(2):
        session.add(_devis_similaire(i + 1, 10.0))
    session.flush()
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_003, MATIERE, session)
    assert "ecart_historique" not in _regles(constats)


def test_bornes_absentes_controles_ignores(session, chiffrage_003, flan_003):
    """Une borne absente de la table → contrôle ignoré, pas d'erreur."""
    for borne in session.query(BorneControle).all():
        session.delete(borne)
    session.flush()
    constats = evaluer_controles_prix(chiffrage_003, piece_support(), flan_003, MATIERE, session)
    assert "prix_au_kg" not in _regles(constats)
    assert "part_matiere" not in _regles(constats)
    assert "ecart_historique" not in _regles(constats)
