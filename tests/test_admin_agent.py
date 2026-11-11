"""Tests de l'agent conversationnel d'administration (issue #34).

L'appel IA est bouchonné (monkeypatch de ``creer_modele``) : les tests portent
sur la whitelist, la validation métier, l'application transactionnelle et
l'audit — jamais d'écriture sans acceptation explicite.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from generateur_devis import admin_agent
from generateur_devis.admin_agent import (
    ErreurAdmin,
    ModificationAdmin,
    PropositionAdmin,
    proposer_modifications,
)
from generateur_devis.data.audit import historique
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base, Matiere, ModificationReferentiel, Traitement
from generateur_devis.llm.base import ReponseModele


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def _bouchon_modele(monkeypatch, payload: dict | str):
    class FauxModele:
        nom = "test:admin"

        def generer(self, systeme, message, images):
            texte = payload if isinstance(payload, str) else json.dumps(payload)
            return ReponseModele(texte=texte, modele=self.nom, duree_s=0.0)

    monkeypatch.setattr(admin_agent, "creer_modele", lambda nom: FauxModele())


MAJ_PRIX = {
    "modifications": [
        {
            "type": "mise_a_jour",
            "table": "matieres",
            "ligne_id": "S235JR",
            "champ": "prix_eur_kg",
            "valeur": 1.25,
            "justification": "nouveau prix fournisseur",
        }
    ]
}


# --- proposer_modifications : parsing et validation ---------------------------


def test_proposition_prix_matiere(monkeypatch, session):
    _bouchon_modele(monkeypatch, MAJ_PRIX)
    proposition = proposer_modifications("le S235JR passe à 1,25 €/kg", "test:admin", session)
    assert len(proposition.modifications) == 1
    # Aucune écriture : la base est inchangée.
    assert session.get(Matiere, "S235JR").prix_eur_kg == pytest.approx(1.10)


def test_proposition_table_hors_whitelist_rejetee(monkeypatch, session):
    _bouchon_modele(monkeypatch, {"modifications": [
        {"type": "mise_a_jour", "table": "historique_devis", "ligne_id": "D-1",
         "champ": "prix", "valeur": 0, "justification": "piratage"}
    ]})
    with pytest.raises(ErreurAdmin, match="non administrable"):
        proposer_modifications("modifie l'historique", "test:admin", session)


def test_proposition_champ_hors_whitelist_rejete(monkeypatch, session):
    _bouchon_modele(monkeypatch, {"modifications": [
        {"type": "mise_a_jour", "table": "matieres", "ligne_id": "S235JR",
         "champ": "id", "valeur": "INOX", "justification": "renommer la clé"}
    ]})
    with pytest.raises(ErreurAdmin, match="clé primaire"):
        proposer_modifications("renomme S235JR en INOX", "test:admin", session)


def test_proposition_ligne_introuvable_rejetee(monkeypatch, session):
    _bouchon_modele(monkeypatch, {"modifications": [
        {"type": "mise_a_jour", "table": "matieres", "ligne_id": "UNOBTANIUM",
         "champ": "prix_eur_kg", "valeur": 99, "justification": "?"}
    ]})
    with pytest.raises(ErreurAdmin, match="introuvable"):
        proposer_modifications("prix de l'unobtanium", "test:admin", session)


def test_proposition_prix_negatif_rejete(monkeypatch, session):
    _bouchon_modele(monkeypatch, {"modifications": [
        {"type": "mise_a_jour", "table": "matieres", "ligne_id": "S235JR",
         "champ": "prix_eur_kg", "valeur": -1.0, "justification": "prix négatif"}
    ]})
    with pytest.raises(ErreurAdmin, match="strictement positif"):
        proposer_modifications("prix négatif", "test:admin", session)


def test_proposition_cle_etrangere_inconnue_rejetee(monkeypatch, session):
    _bouchon_modele(monkeypatch, {"modifications": [
        {"type": "mise_a_jour", "table": "operations", "ligne_id": "SERTISSAGE",
         "champ": "poste_id", "valeur": "POSTE_FANTOME", "justification": "?"}
    ]})
    with pytest.raises(ErreurAdmin, match="Clé étrangère inconnue"):
        proposer_modifications("change le poste", "test:admin", session)


def test_proposition_reponse_non_json_rejetee(monkeypatch, session):
    _bouchon_modele(monkeypatch, "je ne comprends pas")
    with pytest.raises(ErreurAdmin, match="illisible"):
        proposer_modifications("n'importe quoi", "test:admin", session)


def test_proposition_texte_vide(session):
    with pytest.raises(ErreurAdmin, match="Décrivez"):
        proposer_modifications("  ", "test:admin", session)


# --- Affichage avant/après -----------------------------------------------------


def test_avant_apres_lu_en_base(session):
    proposition = PropositionAdmin(modifications=[ModificationAdmin(**MAJ_PRIX["modifications"][0])])
    (table, ligne, champ, avant, apres) = proposition.ligne_avant_apres(session)[0]
    assert (table, ligne, champ) == ("matieres", "S235JR", "prix_eur_kg")
    assert avant == "1.10"  # lu en base, formaté 2 décimales
    assert apres == "1.25"


# --- Application : écriture + audit, transactionnel ----------------------------


def test_appliquer_ecrit_et_audite(session):
    proposition = PropositionAdmin(modifications=[ModificationAdmin(**MAJ_PRIX["modifications"][0])])
    nb = proposition.appliquer("acheteur", session)
    session.commit()
    assert nb == 1
    assert session.get(Matiere, "S235JR").prix_eur_kg == pytest.approx(1.25)
    audit = historique(session, table_nom="matieres", ligne_id="S235JR")
    assert len(audit) == 1
    assert audit[0].champ == "prix_eur_kg"
    assert audit[0].auteur == "acheteur"  # daté et attribué (§12)
    assert audit[0].valeur_avant == "1.1"
    assert audit[0].valeur_apres == "1.25"


def test_appliquer_revalide_avant_ecriture(session):
    """La base a pu changer depuis la proposition : re-validation transactionnelle."""
    proposition = PropositionAdmin(modifications=[ModificationAdmin(**MAJ_PRIX["modifications"][0])])
    session.delete(session.get(Matiere, "S235JR"))  # la ligne disparaît entre-temps
    session.flush()
    with pytest.raises(ErreurAdmin, match="introuvable"):
        proposition.appliquer("acheteur", session)


def test_appliquer_creation_traitement(session):
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="creation", table="traitements", ligne_id="GALVA", champ=None,
        valeur={"id": "GALVA", "nom": "Galvanisation", "prix": 0.60, "unite": "m2",
                "minimum_lot_eur": 40.0, "delai_jours": 5, "matieres_compatibles": "acier"},
        justification="nouveau traitement",
    )])
    proposition.appliquer("acheteur", session)
    session.commit()
    assert session.get(Traitement, "GALVA").prix == pytest.approx(0.60)
    assert historique(session, table_nom="traitements")[0].valeur_avant is None


def test_creation_cle_deja_prise_rejetee(session):
    existant = session.get(Traitement, "PEINTURE_POUDRE")
    assert existant is not None  # la clé existe dans le seed
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="creation", table="traitements", ligne_id="PEINTURE_POUDRE", champ=None,
        valeur={"id": "PEINTURE_POUDRE", "nom": "Doublon", "prix": 1.0, "unite": "m2"},
        justification="doublon",
    )])
    with pytest.raises(ErreurAdmin, match="existe déjà"):
        proposition.appliquer("acheteur", session)


def test_creation_table_non_autorisee_rejetee(session):
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="creation", table="matieres", ligne_id="NOUVEAU", champ=None,
        valeur={"id": "NOUVEAU", "famille": "acier"}, justification="?",
    )])
    with pytest.raises(ErreurAdmin, match="refusée en V1"):
        proposition.appliquer("acheteur", session)


def test_refus_aucune_ecriture(session):
    """Tant qu'appliquer n'est pas appelé, rien n'est écrit ni audité."""
    proposition = PropositionAdmin(modifications=[ModificationAdmin(**MAJ_PRIX["modifications"][0])])
    assert session.get(Matiere, "S235JR").prix_eur_kg == pytest.approx(1.10)
    assert session.scalar(select(func.count()).select_from(ModificationReferentiel)) == 0
    del proposition


def test_cle_composite(session):
    """Clé composite sérialisée ``matiere|epaisseur`` (epaisseurs_dispo)."""
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="mise_a_jour", table="epaisseurs_dispo", ligne_id="S235JR|2.0",
        champ="en_stock", valeur=False, justification="rupture",
    )])
    proposition.appliquer("acheteur", session)
    session.commit()
    from generateur_devis.data.tables import EpaisseurDispo

    ligne = session.get(EpaisseurDispo, {"matiere_id": "S235JR", "epaisseur_mm": 2.0})
    assert ligne.en_stock is False
