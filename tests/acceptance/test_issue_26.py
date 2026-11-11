"""Tests d'acceptance de l'issue #26 : restitution, PDF client, émission.

Couverture des critères (1:1) — les critères déjà couverts par les tests
unitaires sont référencés, pas dupliqués :
- Vue interne (blocs, paliers, marge, trace) → test_rechiffrage_vue_interne
- Vue client (désignation, prix, options, validité) → tests/test_pdf.py
- Conditions générales dans le PDF → test_pdf_contient_les_conditions
- Marge modifiée rechiffrée et journalisée → tests/test_devis.py (4.1)
- PDF sans coût ni marge → tests/test_pdf.py (assertion négative)
- Émission idempotente refusée → test_emission_bout_en_bout_et_idempotente
"""

from __future__ import annotations

from datetime import datetime

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, HistoriqueDevis
from generateur_devis.devis import Devis, ErreurDevis, emettre
from generateur_devis.pdf import generer_pdf_client
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui.pipeline import rechiffrer

MATIERE = "S235JR"


def piece_support() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur=MATIERE), epaisseur=Champ[float](valeur=2.0)
        ),
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
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
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


def devis_valide(session) -> tuple[Devis, object]:
    resultat = rechiffrer(piece_support(), MATIERE, None, [1, 100], session)
    devis = Devis(
        id="D-2026-ACC",
        matiere_id=MATIERE,
        piece_validee=piece_support(),
        chiffrage=resultat.chiffrage,
        marge=0.25,
        quantite_commandee=100,
        date_creation=datetime(2026, 11, 11),
    )
    devis.valider("testeur")
    return devis, resultat.flan


def test_rechiffrage_vue_interne(session):
    """Vue interne : blocs de coût, paliers, trace et alertes sont produits."""
    resultat = rechiffrer(piece_support(), MATIERE, None, [1, 100], session)
    chiffrage = resultat.chiffrage
    assert chiffrage.blocs_1_3.matiere is not None
    assert chiffrage.blocs_4_6.composants is not None
    assert len(chiffrage.paliers) == 2
    assert len(chiffrage.trace) > 0  # tracé complet du calcul
    assert isinstance(resultat.alertes_controles, list)  # comparaison historique §6


def test_pdf_contient_les_conditions(session):
    """Vue client : les conditions générales (paramètre) figurent dans le PDF."""
    devis, _ = devis_valide(session)
    contenu = generer_pdf_client(devis, validite_jours=30, conditions="Prix HT.")
    with fitz.open(stream=contenu, filetype="pdf") as doc:
        texte = "".join(page.get_text() for page in doc)
    assert "Prix HT." in texte


def test_emission_bout_en_bout_et_idempotente(session):
    """Émission : statut « emis » + ligne historique ; un devis émis n'est plus modifiable."""
    devis, flan = devis_valide(session)
    ligne = emettre(devis, flan, "testeur", session)
    assert devis.statut == "emis"
    assert isinstance(ligne, HistoriqueDevis)
    assert ligne.id == devis.id
    # Idempotente : une deuxième émission est refusée.
    with pytest.raises(ErreurDevis):
        emettre(devis, flan, "testeur", session)
    # Lecture seule : plus aucune modification possible.
    with pytest.raises(ErreurDevis):
        devis.changer_marge("testeur", 0.30)
