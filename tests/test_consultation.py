"""Consultation en lecture seule des référentiels administrables (issue #94)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from generateur_devis.admin_agent import REFERENTIELS_MODIFIABLES
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, BorneControle
from generateur_devis.ui.consultation import (
    LIBELLES_TABLES,
    colonnes_consultables,
    consulter_referentiel,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, class_=Session)() as s:
        seed(s)
        s.commit()
        yield s


def test_chaque_table_de_la_whitelist_est_consultable(session):
    """Garde-fou : toute table ajoutée à la whitelist doit avoir un libellé."""
    assert set(LIBELLES_TABLES) == set(REFERENTIELS_MODIFIABLES)
    assert "historique_devis" not in LIBELLES_TABLES
    for table, referentiel in REFERENTIELS_MODIFIABLES.items():
        attendues = [*referentiel.pk, *referentiel.champs]
        assert colonnes_consultables(table) == attendues
        lignes = consulter_referentiel(table, session)
        assert lignes, table  # chaque table est seedée
        for ligne in lignes:
            assert list(ligne) == attendues, table


def test_libelles_lisibles_et_non_sql():
    for table, libelle in LIBELLES_TABLES.items():
        assert libelle != table
        assert "_" not in libelle


def test_valeurs_seedees_formatees(session):
    matieres = {m["id"]: m for m in consulter_referentiel("matieres", session)}
    s235 = matieres["S235JR"]
    assert s235["prix_eur_kg"] == "1.10"
    assert s235["densite_kg_dm3"] == "7.850"
    assert s235["famille"] == "acier"
    assert s235["norme"] == "EN 10025-2"
    assert "date_maj" not in s235  # hors whitelist : non affiché

    postes = {p["id"]: p for p in consulter_referentiel("postes", session)}
    assert postes["LASER_3KW"]["taux_horaire_eur_h"] == "120.00"
    assert postes["LASER_3KW"]["temps_reglage_min"] == "15.00"

    epaisseurs = consulter_referentiel("epaisseurs_dispo", session)
    premiere = next(e for e in epaisseurs if e["matiere_id"] == "S235JR")
    assert premiere["epaisseur_mm"] == "1.00"
    assert premiere["en_stock"] == "oui"


def test_lignes_triees_par_cle(session):
    ids = [m["id"] for m in consulter_referentiel("matieres", session)]
    assert ids == sorted(ids)

    # PK composite : tri numérique sur l'épaisseur, pas lexical sur le texte.
    epaisseurs = [
        float(e["epaisseur_mm"])
        for e in consulter_referentiel("epaisseurs_dispo", session)
        if e["matiere_id"] == "S235JR"
    ]
    assert epaisseurs == sorted(epaisseurs)
    assert len(epaisseurs) > 2


def test_table_vide_liste_vide(session):
    session.query(BorneControle).delete()
    session.commit()
    assert consulter_referentiel("bornes_controle", session) == []


def test_table_hors_whitelist_refusee(session):
    with pytest.raises(ValueError):
        consulter_referentiel("historique_devis", session)
    with pytest.raises(ValueError):
        colonnes_consultables("historique_devis")
