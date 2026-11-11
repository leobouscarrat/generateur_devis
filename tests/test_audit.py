"""Tests du socle d'audit des référentiels (issue #33, architecture §12).

Toute modification d'un référentiel est datée et attribuée ; les devis émis
ne sont pas affectés (non-régression sur `emettre`, 4.1).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.audit import (
    ErreurAudit,
    enregistrer_modification,
    historique,
)
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, ModificationReferentiel
from generateur_devis.devis import Devis, emettre
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


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def test_enregistrement_date_et_attribue(session):
    ligne = enregistrer_modification(
        "matieres", "S235JR", "prix_kg_eur", 1.10, 1.25, "acheteur", session
    )
    session.commit()
    assert ligne.id is not None
    assert ligne.auteur == "acheteur"
    assert isinstance(ligne.date, datetime)  # datée automatiquement
    assert ligne.valeur_avant == "1.1"
    assert ligne.valeur_apres == "1.25"


def test_enregistrement_creation_et_suppression(session):
    """Création → avant=None ; suppression → après=None."""
    creation = enregistrer_modification(
        "traitements", "GALVA", "designation", None, "Galvanisation", "acheteur", session
    )
    suppression = enregistrer_modification(
        "traitements", "GALVA", "designation", "Galvanisation", None, "acheteur", session
    )
    assert creation.valeur_avant is None
    assert suppression.valeur_apres is None


def test_auteur_obligatoire(session):
    with pytest.raises(ErreurAudit, match="anonyme"):
        enregistrer_modification("matieres", "S235JR", "prix_kg_eur", 1.1, 1.2, "  ", session)


def test_historique_filtre_et_trie(session):
    enregistrer_modification("matieres", "S235JR", "prix_kg_eur", 1.10, 1.25, "a", session)
    enregistrer_modification("matieres", "S235JR", "densite", 7.85, 7.86, "b", session)
    enregistrer_modification("postes", "LASER_3KW", "taux_horaire", 120, 130, "c", session)
    session.commit()

    toutes = historique(session)
    assert len(toutes) == 3
    assert [m.date for m in toutes] == sorted(
        (m.date for m in toutes), reverse=True
    )  # plus récent d'abord

    matieres = historique(session, table_nom="matieres")
    assert len(matieres) == 2
    s235 = historique(session, table_nom="matieres", ligne_id="S235JR")
    assert len(s235) == 2
    assert historique(session, ligne_id="LASER_3KW")[0].champ == "taux_horaire"


def test_emission_devis_ne_cree_pas_d_audit(session):
    """Non-régression : l'émission d'un devis n'écrit pas dans l'audit (prix figés)."""
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
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
    )
    resultat = rechiffrer(piece, "S235JR", None, [100], session)
    devis = Devis(
        id="D-AUDIT",
        matiere_id="S235JR",
        piece_validee=piece,
        chiffrage=resultat.chiffrage,
        flan=resultat.flan,
        marge=0.25,
        quantite_commandee=100,
        date_creation=datetime(2026, 11, 11),
    )
    devis.valider("testeur")
    emettre(devis, "testeur", session)
    session.commit()
    nb = session.scalar(select(func.count()).select_from(ModificationReferentiel))
    assert nb == 0
