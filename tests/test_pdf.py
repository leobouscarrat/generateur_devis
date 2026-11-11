"""Tests du PDF client (issue #26).

Le PDF est la **vue client** : prix et quantités seulement — aucun coût,
aucune marge, aucun tracé de calcul (architecture §6). Le texte est relu
avec pymupdf (déjà dépendance de test) pour des assertions sur le contenu
réel du document.
"""

from __future__ import annotations

from datetime import datetime

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.calcul_prix import BlocFinition, chiffrer
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.devis import Devis
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


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def devis_test(session) -> Devis:
    piece = PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
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
    piece.identification.designation.valeur = "Support"
    piece.identification.reference.valeur = "SUP-01"
    return Devis(
        id="D-2026-0001",
        client_id="CLI001",
        matiere_id="S235JR",
        piece_validee=piece,
        chiffrage=chiffrer(piece, "S235JR", session, quantites=[1, 100]),
        marge=0.25,
        quantite_commandee=100,
        statut="valide",
        date_creation=datetime(2026, 11, 11),
        options=[
            BlocFinition(
                traitement_id="PEINTURE",
                surface_traitee_m2=0.01,
                prix=0.40,
                unite="m2",
                minimum_lot_eur=25.0,
                cout_variable_eur=0.004,
                cout_fixe_eur_par_lot=25.0,
            )
        ],
    )


def _texte_pdf(contenu: bytes) -> str:
    with fitz.open(stream=contenu, filetype="pdf") as doc:
        return "".join(page.get_text() for page in doc)


def test_pdf_est_un_document_valide(session):
    contenu = generer_pdf_client(devis_test(session), validite_jours=30)
    assert contenu.startswith(b"%PDF")
    assert len(contenu) > 500


def test_pdf_contient_la_vue_client(session):
    devis = devis_test(session)
    texte = _texte_pdf(generer_pdf_client(devis, validite_jours=30))
    assert "D-2026-0001" in texte
    assert "Support" in texte
    assert "SUP-01" in texte
    assert "S235JR" in texte
    assert "11/12/2026" in texte  # 11/11 + 30 jours de validité
    # Prix par palier (unitaire et total), relus depuis le devis lui-même.
    for palier in devis.chiffrage.paliers:
        assert f"{palier.prix_unitaire_eur:.2f}" in texte
        assert f"{palier.prix_unitaire_eur * palier.quantite:.2f}" in texte
    # Option chiffrée à part : max(0.40, 25 ÷ 100) = 0.40.
    assert "PEINTURE" in texte
    assert "0.40" in texte


def test_pdf_ne_divulgue_aucun_cout_ni_marge(session):
    """Vue client : les coûts bruts et la marge ne sortent jamais (§6)."""
    devis = devis_test(session)
    texte = _texte_pdf(generer_pdf_client(devis, validite_jours=30))
    for palier in devis.chiffrage.paliers:
        assert f"{palier.cout_unitaire_eur:.2f}" not in texte
    assert "marge" not in texte.lower()
    assert "coût" not in texte.lower() and "cout" not in texte.lower()


def test_pdf_option_minimum_de_lot(session):
    """À Q=1, l'option est au minimum de lot : max(0.40, 25 ÷ 1) = 25 €."""
    devis = devis_test(session).model_copy(update={"quantite_commandee": 1})
    texte = _texte_pdf(generer_pdf_client(devis, validite_jours=30))
    assert "25.00" in texte
