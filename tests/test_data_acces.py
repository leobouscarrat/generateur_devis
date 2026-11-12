"""Tests de la couche d'accès typée Pydantic (issue #3)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.acces import (
    TYPE_COMPOSANT_PAR_TYPE_EXTRAIT,
    get_bornes,
    get_client,
    get_composant,
    get_matiere,
    get_parametre,
    get_poste,
    get_temps_pliage,
    get_traitement,
    get_vitesse_coupe,
    list_composants,
    list_epaisseurs,
    list_historique_similaires,
)
from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base


@pytest.fixture
def session():
    """Fixture SQLite en mémoire pour les tests d'accès de données."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_session(session):
    """Fixture avec base seedée pour les tests."""
    seed(session)
    return session


# ---------- Modèles Pydantic : extra="forbid" ----------


def test_matiere_extra_forbid():
    """MatierePydantic rejette les champs inconnus."""
    from generateur_devis.data.acces import MatierePydantic

    with pytest.raises(ValueError):
        MatierePydantic(id="X", inconnue="y")  # type: ignore[arg-type]


def test_borne_extra_forbid():
    """BorneControlePydantic rejette les champs inconnus."""
    from generateur_devis.data.acces import BorneControlePydantic

    with pytest.raises(ValueError):
        BorneControlePydantic(champ="x", min=0, max=1, niveau="alerte", message="t", champ2="y")  # type: ignore[arg-type]


# ---------- get_matiere ----------


def test_get_matiere_nominal(seeded_session):
    """get_matiere retourne un MatierePydantic connu."""
    result = get_matiere("S235JR", seeded_session)
    assert result is not None
    assert result.id == "S235JR"
    assert result.famille == "acier"


def test_get_matiere_inconnu(seeded_session):
    """get_matiere retourne None pour un identifiant inconnu."""
    result = get_matiere("EXISTE_PAS", seeded_session)
    assert result is None


# ---------- list_epaisseurs ----------


def test_list_epaisseurs_nominal(seeded_session):
    """list_epaisseurs retourne la liste des épaisseurs pour S235JR."""
    result = list_epaisseurs("S235JR", seeded_session)
    assert isinstance(result, list)
    assert len(result) > 0


def test_list_epaisseurs_matiere_inconnue(seeded_session):
    """list_epaisseurs retourne [] pour une matière inexistante."""
    result = list_epaisseurs("EXISTE_PAS", seeded_session)
    assert result == []


# ---------- get_poste ----------


def test_get_poste_nominal(seeded_session):
    """get_poste retourne un PostePydantic connu."""
    result = get_poste("LASER_3KW", seeded_session)
    assert result is not None
    assert result.id == "LASER_3KW"
    assert result.nom == "Laser fibre 3 kW"


def test_get_poste_inconnu(seeded_session):
    """get_poste retourne None pour un identifiant inconnu."""
    result = get_poste("EXISTE_PAS", seeded_session)
    assert result is None


# ---------- get_vitesse_coupe ----------


def test_get_vitesse_coupe_nominal(seeded_session):
    """get_vitesse_coupe retourne une VitesseCoupePydantic connue."""
    result = get_vitesse_coupe("LASER_3KW", "acier", 2.0, seeded_session)
    assert result is not None
    assert result.poste_id == "LASER_3KW"
    assert result.famille == "acier"
    assert result.epaisseur_mm == 2.0


def test_get_vitesse_coupe_inconnu(seeded_session):
    """get_vitesse_coupe retourne None pour des clés inconnues."""
    result = get_vitesse_coupe("EXISTE_PAS", "acier", 2.0, seeded_session)
    assert result is None


def test_get_vitesse_coupe_famille_inconnue(seeded_session):
    """get_vitesse_coupe retourne None pour une famille inconnue avec cette épaisseur."""
    result = get_vitesse_coupe("LASER_3KW", "inox", 99.9, seeded_session)
    assert result is None


# ---------- get_temps_pliage ----------


def test_get_temps_pliage_dans_capacite(seeded_session):
    """get_temps_pliage retourne le bonne tranche pour acier 2mm (catégorie petite)."""
    result = get_temps_pliage(250.0, 2.0, seeded_session)
    assert result is not None
    assert result.categorie == "petite"
    assert result.dim_max_mm == 300


def test_get_temps_pliage_hors_capacite(seeded_session):
    """get_temps_pliage retourne None dimension trop grande."""
    result = get_temps_pliage(5000.0, 20.0, seeded_session)
    assert result is None


# ---------- get_composant ----------


def test_get_composant_nominal(seeded_session):
    """get_composant retourne un ComposantPydantic connu."""
    result = get_composant("ES-M6-A", seeded_session)
    assert result is not None
    assert result.reference == "ES-M6-A"
    assert result.designation == "Écrou à sertir M6"


def test_get_composant_inconnu(seeded_session):
    """get_composant retourne None pour une référence inconnue."""
    result = get_composant("EXISTE_PAS", seeded_session)
    assert result is None


# ---------- get_traitement ----------


def test_get_traitement_nominal(seeded_session):
    """get_traitement retourne un TraitementPydantic connu."""
    result = get_traitement("PEINTURE_POUDRE", seeded_session)
    assert result is not None
    assert result.id == "PEINTURE_POUDRE"
    assert result.nom == "Thermolaquage 1 couche"


def test_get_traitement_inconnu(seeded_session):
    """get_traitement retourne None pour un identifiant inconnu."""
    result = get_traitement("EXISTE_PAS", seeded_session)
    assert result is None


# ---------- get_parametre ----------


def test_get_parametre_marge_defaut(seeded_session):
    """get_parametre('marge_defaut') retourne un float."""
    result = get_parametre("marge_defaut", seeded_session)
    assert isinstance(result, float)
    assert result == 0.25


def test_get_parametre_rendement_calepinage(seeded_session):
    """get_parametre('rendement_calepinage') retourne un float."""
    result = get_parametre("rendement_calepinage", seeded_session)
    assert isinstance(result, float)
    assert result == 0.80


def test_get_parametre_facteur_k(seeded_session):
    """get_parametre('facteur_k') retourne un float."""
    result = get_parametre("facteur_k", seeded_session)
    assert isinstance(result, float)
    assert result == 0.40


def test_get_parametre_frais_structure_pct(seeded_session):
    """get_parametre('frais_structure_pct') retourne un int (0)."""
    result = get_parametre("frais_structure_pct", seeded_session)
    assert isinstance(result, int)
    assert result == 0


def test_get_parametre_minimum_commande_eur(seeded_session):
    """get_parametre('minimum_commande_eur') retourne un int."""
    result = get_parametre("minimum_commande_eur", seeded_session)
    assert isinstance(result, int)


def test_get_parametre_validite_devis_jours(seeded_session):
    """get_parametre('validite_devis_jours') retourne un int."""
    result = get_parametre("validite_devis_jours", seeded_session)
    assert isinstance(result, int)


def test_get_parametre_paliers_quantite(seeded_session):
    """get_parametre('paliers_quantite') retourne un list[int]."""
    result = get_parametre("paliers_quantite", seeded_session)
    assert isinstance(result, list)
    assert result == [1, 10, 100, 1000]


def test_get_parametre_devise(seeded_session):
    """get_parametre('devise') retourne une str."""
    result = get_parametre("devise", seeded_session)
    assert isinstance(result, str)
    assert result == "EUR"


def test_get_parametre_inconnu(seeded_session):
    """get_parametre clé inconnue lève ValueError."""
    from generateur_devis.data.acces import get_parametre
    with pytest.raises(ValueError):
        get_parametre("EXISTE_PAS", seeded_session)


# ---------- get_client ----------


def test_get_client_nominal(seeded_session):
    """get_client retourne un ClientPydantic connu."""
    result = get_client("CLI001", seeded_session)
    assert result is not None
    assert result.id == "CLI001"
    assert result.nom == "Client Alpha"


def test_get_client_inconnu(seeded_session):
    """get_client retourne None pour un identifiant inconnu."""
    result = get_client("EXISTE_PAS", seeded_session)
    assert result is None


# ---------- get_bornes ----------


def test_get_bornes_nominal(seeded_session):
    """get_bornes retourne la liste complète des bornes."""
    result = get_bornes(seeded_session)
    assert isinstance(result, list)
    assert len(result) > 0
    assert result[0].champ == "epaisseur_mm"


def test_get_bornes_tous_presentes(seeded_session):
    """Vérifie que toutes les bornes de contrôle attendues sont présentes."""
    result = get_bornes(seeded_session)
    noms = {b.champ for b in result}
    expected = {"epaisseur_mm", "flan_dim_max_mm", "ratio_surface_dev_surface_vue",
                "ratio_longueur_coupe_périmètre_flan", "ecart_masse_calculee_pct",
                "prix_eur_kg_masse_gt_1kg", "prix_eur_kg_masse_le_1kg",
                "part_matiere_pct_qte_gte_100", "ecart_historique_pct", "marge"}
    assert noms == expected


# ---------- list_historique_similaires ----------


def test_list_historique_similaires_nominal(seeded_session):
    """list_historique_similaires retourne des lignes avec filtres de base."""
    result = list_historique_similaires(session=seeded_session)
    assert isinstance(result, list)


def test_list_historique_similaires_filtre_matiere(seeded_session):
    """list_historique_similaires filtre par matiere_id."""
    result = list_historique_similaires(
        session=seeded_session, matiere_id="S235JR"
    )
    assert isinstance(result, list)
    # Tous les résultats doivent avoir la bonne matière
    for ligne in result:
        assert ligne.matiere_id == "S235JR"


def test_list_historique_similaires_filtre_traitement(seeded_session):
    """list_historique_similaires filtre par traitement_id."""
    result = list_historique_similaires(
        session=seeded_session, traitement_id="PEINTURE_POUDRE"
    )
    assert isinstance(result, list)
    for ligne in result:
        assert ligne.traitement_id == "PEINTURE_POUDRE"


def test_list_historique_similaires_filtre_quantite(seeded_session):
    """list_historique_similaires filtre par fourchette de quantité."""
    result = list_historique_similaires(
        session=seeded_session, quantite_min=10, quantite_max=100
    )
    assert isinstance(result, list)
    for ligne in result:
        assert 10 <= ligne.quantite <= 100


def test_list_historique_similaires_tous_criteres(seeded_session):
    """list_historique_similaires avec tous les critères combinés."""
    result = list_historique_similaires(
        session=seeded_session,
        matiere_id="DC01",
        traitement_id="CATAPHORESE",
        quantite_min=1,
        quantite_max=50,
    )
    assert isinstance(result, list)
    for ligne in result:
        assert ligne.matiere_id == "DC01"
        assert ligne.traitement_id == "CATAPHORESE"
        assert 1 <= ligne.quantite <= 50


# ---------- Cas limites divers ----------


def test_identifiant_inconnu_retourne_none(seeded_session):
    """Tous les get_* avec identifiant inconnu renvoient None (uniforme)."""
    # get_matiere
    assert get_matiere("EXISTE_PAS", seeded_session) is None
    # get_poste
    assert get_poste("EXISTE_PAS", seeded_session) is None
    # get_composant
    assert get_composant("EXISTE_PAS", seeded_session) is None
    # get_traitement
    assert get_traitement("EXISTE_PAS", seeded_session) is None
    # get_client
    assert get_client("EXISTE_PAS", seeded_session) is None


# ---------- list_composants (issue #56) ----------


def test_list_composants_tous_tries(seeded_session):
    """Les 8 références seedées, triées par référence."""
    references = [c.reference for c in list_composants(seeded_session)]
    assert references == [
        "ENT-M4-10",
        "ES-M4-A",
        "ES-M5-A",
        "ES-M6-A",
        "ES-M6-B",
        "ES-M6-X",
        "ES-M8-A",
        "GS-M6-A",
    ]


def test_list_composants_champs(seeded_session):
    lot = next(c for c in list_composants(seeded_session) if c.reference == "ES-M6-B")
    assert lot.designation == "Écrou à sertir M6 (lot 1000)"
    assert lot.type == "ecrou_sertir"
    assert lot.filetage == "M6"
    assert lot.prix_unitaire_eur == pytest.approx(0.15)
    assert lot.qte_min == 1000


def test_type_composant_par_type_extrait_garde_fou(seeded_session):
    """Clés = littéraux de Composant.type ; valeurs = types du référentiel seedé."""
    import typing

    from generateur_devis.schema.piece import Composant

    litteraux = set(typing.get_args(Composant.model_fields["type"].annotation))
    assert set(TYPE_COMPOSANT_PAR_TYPE_EXTRAIT) <= litteraux
    types_referentiel = {c.type for c in list_composants(seeded_session)}
    assert set(TYPE_COMPOSANT_PAR_TYPE_EXTRAIT.values()) <= types_referentiel
