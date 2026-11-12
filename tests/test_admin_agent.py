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
    REFERENTIELS_MODIFIABLES,
    ErreurAdmin,
    ModificationAdmin,
    PropositionAdmin,
    proposer_modifications,
)
from generateur_devis.data.acces import get_parametre
from generateur_devis.data.audit import historique
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import (
    Base,
    Client,
    Matiere,
    ModificationReferentiel,
    Traitement,
)
from generateur_devis.extraction.prompt import (
    prompt_systeme_admin,
    prompt_utilisateur_admin,
)
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


def test_coercition_bool_chaine(session):
    """« false » en chaîne doit donner False — bool(\"false\") vaut True sinon."""
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="mise_a_jour", table="epaisseurs_dispo", ligne_id="S235JR|2.0",
        champ="en_stock", valeur="false", justification="rupture",
    )])
    proposition.appliquer("acheteur", session)
    from generateur_devis.data.tables import EpaisseurDispo

    ligne = session.get(EpaisseurDispo, {"matiere_id": "S235JR", "epaisseur_mm": 2.0})
    assert ligne.en_stock is False


def test_rayon_pliage_defaut_parametre_administrable(session):
    """Le rayon de pliage proposé par défaut est un paramètre administrable
    (utilisé quand le plan ne cote aucun rayon, ni par pli ni en note générale)."""
    from generateur_devis.data.acces import get_parametre

    assert get_parametre("rayon_pliage_defaut_mm", session) == 1.0
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="mise_a_jour", table="parametres", ligne_id="rayon_pliage_defaut_mm",
        champ="valeur", valeur="2.5",
        justification="outil standard R2.5",
    )])
    proposition.appliquer("acheteur", session)
    session.commit()
    assert get_parametre("rayon_pliage_defaut_mm", session) == 2.5


def test_modele_extraction_parametre_administrable(session):
    """Le modèle d'extraction est un paramètre base modifiable par l'agent."""
    from generateur_devis.data.acces import get_parametre

    assert get_parametre("modele_extraction", session) == "claude-code:sonnet"
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="mise_a_jour", table="parametres", ligne_id="modele_extraction",
        champ="valeur", valeur="openrouter:modele-vision",
        justification="bascule fournisseur",
    )])
    proposition.appliquer("direction", session)
    session.commit()
    assert get_parametre("modele_extraction", session) == "openrouter:modele-vision"


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


# --- Marges bornées 0 <= marge < 1 (issue #71) --------------------------------


def _maj(table: str, ligne_id: str, champ: str, valeur) -> dict:
    return {
        "modifications": [
            {
                "type": "mise_a_jour",
                "table": table,
                "ligne_id": ligne_id,
                "champ": champ,
                "valeur": valeur,
                "justification": "test",
            }
        ]
    }


@pytest.mark.parametrize("valeur", ["1", "1.0", "1.5", "-0.1", "nan", "inf"])
def test_marge_defaut_hors_bornes_refusee_a_la_proposition(monkeypatch, session, valeur):
    _bouchon_modele(monkeypatch, _maj("parametres", "marge_defaut", "valeur", valeur))
    with pytest.raises(ErreurAdmin, match="Marge invalide"):
        proposer_modifications("marge par défaut", "test:admin", session)
    assert get_parametre("marge_defaut", session) == 0.25


@pytest.mark.parametrize("valeur", ["25 %", "0,25", "abc"])
def test_marge_defaut_non_numerique_refusee(monkeypatch, session, valeur):
    _bouchon_modele(monkeypatch, _maj("parametres", "marge_defaut", "valeur", valeur))
    with pytest.raises(ErreurAdmin, match="Marge invalide"):
        proposer_modifications("marge par défaut à 25 %", "test:admin", session)
    assert get_parametre("marge_defaut", session) == 0.25


@pytest.mark.parametrize("valeur", [1.0, 25, -0.01, "25 %", "0,18"])
def test_marge_client_hors_bornes_refusee_a_la_proposition(monkeypatch, session, valeur):
    _bouchon_modele(monkeypatch, _maj("clients", "CLI001", "marge_specifique", valeur))
    with pytest.raises(ErreurAdmin, match="Marge invalide"):
        proposer_modifications("marge client", "test:admin", session)
    assert session.get(Client, "CLI001").marge_specifique == 0.18


def test_message_marge_invalide_lisible(monkeypatch, session):
    _bouchon_modele(monkeypatch, _maj("clients", "CLI001", "marge_specifique", 25))
    with pytest.raises(ErreurAdmin) as exc:
        proposer_modifications("marge client à 25 %", "test:admin", session)
    message = str(exc.value)
    assert "clients.marge_specifique" in message
    assert "CLI001" in message
    assert "ex. 0.25 pour 25 %" in message


def test_proposition_multi_lignes_une_marge_invalide_refusee(monkeypatch, session):
    payload = _maj("matieres", "S235JR", "prix_eur_kg", 1.25)
    payload["modifications"] += _maj("parametres", "marge_defaut", "valeur", "1.2")["modifications"]
    _bouchon_modele(monkeypatch, payload)
    with pytest.raises(ErreurAdmin, match="Marge invalide"):
        proposer_modifications("prix et marge", "test:admin", session)
    assert session.get(Matiere, "S235JR").prix_eur_kg == pytest.approx(1.10)


@pytest.mark.parametrize("valeur", ["0", "0.999"])
def test_marge_defaut_aux_bornes_acceptee(monkeypatch, session, valeur):
    _bouchon_modele(monkeypatch, _maj("parametres", "marge_defaut", "valeur", valeur))
    proposition = proposer_modifications("marge par défaut", "test:admin", session)
    assert proposition.appliquer("direction", session) == 1
    session.commit()
    assert get_parametre("marge_defaut", session) == float(valeur)
    assert len(historique(session, table_nom="parametres", ligne_id="marge_defaut")) == 1


def test_marge_client_valide_acceptee(monkeypatch, session):
    _bouchon_modele(monkeypatch, _maj("clients", "CLI001", "marge_specifique", 0.3))
    proposition = proposer_modifications("marge CLI001 à 30 %", "test:admin", session)
    proposition.appliquer("direction", session)
    session.commit()
    assert session.get(Client, "CLI001").marge_specifique == 0.3
    audit = historique(session, table_nom="clients", ligne_id="CLI001")
    assert len(audit) == 1
    assert audit[0].valeur_apres == "0.3"


def test_marge_client_zero_acceptee(monkeypatch, session):
    _bouchon_modele(monkeypatch, _maj("clients", "CLI001", "marge_specifique", 0.0))
    proposition = proposer_modifications("marge CLI001 à 0", "test:admin", session)
    assert len(proposition.modifications) == 1


def test_appliquer_revalide_la_marge_sans_audit(session):
    """Proposition construite hors ``proposer_modifications`` : refus avant écriture."""
    proposition = PropositionAdmin(modifications=[ModificationAdmin(
        type="mise_a_jour", table="clients", ligne_id="CLI001",
        champ="marge_specifique", valeur=1.0, justification="test",
    )])
    with pytest.raises(ErreurAdmin, match="Marge invalide"):
        proposition.appliquer("acheteur", session)
    assert session.get(Client, "CLI001").marge_specifique == 0.18
    assert historique(session) == []


def test_clients_et_parametres_non_creables():
    """Garde-fou : la branche création ne passe pas par ``_valider_marge``.

    Si la création est un jour ouverte sur ces tables, brancher le contrôle
    des marges dans la branche création avant de faire passer ce test.
    """
    assert not REFERENTIELS_MODIFIABLES["clients"].creation
    assert not REFERENTIELS_MODIFIABLES["parametres"].creation


def test_prompt_admin_enonce_la_borne_des_marges():
    prompt = prompt_systeme_admin()
    assert "marge_specifique" in prompt
    assert "marge_defaut" in prompt
    assert "0 ≤ marge < 1" in prompt


# --- Index des référentiels fourni à l'agent (issue #77) ----------------------


def test_index_contient_les_libelles_metier(session):
    index = admin_agent.index_referentiels(session)
    assert "S235JR (acier, S235JR, EN 10025-2)" in index
    assert "LASER_3KW (Laser fibre 3 kW)" in index
    assert "modele_extraction" in index
    assert "CLI001 (Client Alpha)" in index
    assert "ES-M6-A (Écrou à sertir M6)" in index
    assert "S235JR|2.0" in index
    assert "LASER_3KW|acier|1.0" in index
    assert "petite|300|3.0" in index


def test_index_une_ligne_par_table_de_la_whitelist_seulement(session):
    index = admin_agent.index_referentiels(session)
    tables = [ligne.split(" : ")[0].removeprefix("- ") for ligne in index.splitlines()]
    assert tables == list(REFERENTIELS_MODIFIABLES)
    assert "historique_devis" not in index


def test_index_clients_sans_donnees_confidentielles(session):
    assert REFERENTIELS_MODIFIABLES["clients"].colonnes_index == ("nom",)
    index = admin_agent.index_referentiels(session)
    for client in session.scalars(select(Client)).all():
        assert client.secteur not in index
    for colonne in (
        "ia_externe_autorisee", "reutilisation_autorisee", "suppression_si_refus",
        "duree_conservation_plans_jours", "marge_specifique", "secteur",
    ):
        assert colonne not in index


def test_index_sans_valeurs_courantes(session):
    index = admin_agent.index_referentiels(session)
    assert "1.15" not in index  # prix DC01 (€/kg)
    assert "120" not in index  # taux horaire du laser (€/h)
    assert "0.25" not in index  # marge_defaut
    assert "0.18" not in index  # marge spécifique de CLI001


def test_colonnes_index_existent_dans_les_modeles():
    for nom, referentiel in REFERENTIELS_MODIFIABLES.items():
        colonnes = set(referentiel.modele.__table__.c.keys())
        assert set(referentiel.colonnes_index) <= colonnes, nom


def test_index_ids_relisibles_par_trouver_ligne(session):
    """Chaque ligne_id de l'index retrouve sa ligne (piège : clés composites float/int)."""
    index = admin_agent.index_referentiels(session)
    for ligne in index.splitlines():
        table, contenu = ligne.removeprefix("- ").split(" : ", 1)
        for entree in contenu.split(" ; "):
            ligne_id = entree.split(" (")[0]
            assert admin_agent._trouver_ligne(table, ligne_id, session) is not None


def test_index_table_vide(session):
    session.query(Traitement).delete()
    index = admin_agent.index_referentiels(session)
    assert "- traitements : (aucune ligne)" in index


def test_prompt_utilisateur_contient_index_et_demande():
    prompt = prompt_utilisateur_admin("le S235JR passe à 1,25 €/kg", "- matieres : S235JR")
    assert "- matieres : S235JR" in prompt
    assert "« le S235JR passe à 1,25 €/kg »" in prompt


def test_prompt_systeme_demande_d_utiliser_l_index():
    prompt = prompt_systeme_admin()
    assert "index" in prompt
    assert "N'invente jamais un identifiant" in prompt
    # Les créations (règle 3) gardent une clé nouvelle, absente de l'index.
    assert "la clé est nouvelle" in prompt


@pytest.mark.parametrize("designation", ["modele-qui-nexiste-pas", "foo:bar", ""])
def test_modele_mal_configure_erreur_admin_claire(session, designation):
    """#79 : désignation invalide → ErreurAdmin lisible (jamais ValueError brute).

    Le vrai ``creer_modele`` est appelé : il lève avant tout appel réseau.
    """
    with pytest.raises(ErreurAdmin, match="Modèle d'IA mal configuré") as exc:
        proposer_modifications("le S235JR passe à 1,25 €/kg", designation, session)
    assert "modele_extraction" in str(exc.value)
    assert ".py" not in str(exc.value)


def test_modele_sans_cle_api_erreur_admin_claire(monkeypatch, session):
    """#79 (revue) : ``creer_modele`` lève aussi ``ErreurModele`` à la construction
    (clé d'API absente) — elle doit devenir une ErreurAdmin, pas un traceback.

    ``.env`` neutralisé et clé retirée : le vrai ``creer_modele`` lève avant tout
    appel réseau.
    """
    monkeypatch.setattr("generateur_devis.llm.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ErreurAdmin, match="Agent indisponible.*clé d'API manquante"):
        proposer_modifications("le S235JR passe à 1,25 €/kg", "openrouter:modele-x", session)
