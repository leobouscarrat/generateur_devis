"""Couche d'accès typée Pydantic v2 au-dessus des référentiels SQLite.

Cette module fournit des fonctions de lecture uniquement qui retournent des
modèles Pydantic v2 (model_config = ConfigDict(extra="forbid")) au-dessus des
tables SQLAlchemy. Aucune requête SQL n'est effectuée dans le code appelant —
tout passe par ces fonctions.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Modèles Pydantic v2 — miroir des tables SQLAlchemy de tables.py
# Tous ont extra="forbid" pour empêcher des champs inattendus.


class MatierePydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    famille: str = "acier"
    nuance: str | None = None
    norme: str | None = None
    densite_kg_dm3: float = 7.85
    prix_eur_kg: float = 1.10
    date_maj: date = ...  # type: ignore[assignment]  # Pydantic v2 gère date
    fournisseur: str | None = "Fournisseur fictif"

    def __repr__(self) -> str:
        return f"MatierePydantic(id={self.id!r})"


class EpaisseurDispoPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matiere_id: str
    epaisseur_mm: float
    format_mm: str | None = "3000 × 1500"
    surcout_pct: float = 0.0
    en_stock: bool = True

    def __repr__(self) -> str:
        return f"EpaisseurDispoPydantic(matiere_id={self.matiere_id!r}, epaisseur_mm={self.epaisseur_mm!r})"


class PostePydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nom: str
    type: str  # decoupe, pliage, soudure, sertissage, manuel
    taux_horaire_eur_h: float
    temps_reglage_min: float = 15.0

    def __repr__(self) -> str:
        return f"PostePydantic(id={self.id!r})"


class VitesseCoupePydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poste_id: str
    famille: str
    epaisseur_mm: float
    vitesse_m_min: float
    temps_amorcage_s: float = 0.7
    gaz: str | None = "O2"

    def __repr__(self) -> str:
        return f"VitesseCoupePydantic(poste_id={self.poste_id!r}, famille={self.famille!r}, epaisseur_mm={self.epaisseur_mm!r})"


class TempsPliagePydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categorie: str  # petite / moyenne / grande
    dim_max_mm: int
    epaisseur_max_mm: float
    temps_par_pli_s: float
    temps_retournement_s: float = 0.0
    nb_operateurs: int = 1

    def __repr__(self) -> str:
        return f"TempsPliagePydantic(categorie={self.categorie!r}, dim_max_mm={self.dim_max_mm!r}, epaisseur_max_mm={self.epaisseur_max_mm!r})"


class OperationPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nom: str
    poste_id: str | None = None
    temps_s: float
    unite: str  # par mètre, par trou, par pièce

    def __repr__(self) -> str:
        return f"OperationPydantic(id={self.id!r})"


class ComposantPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    designation: str
    type: str  # ecrou_sertir, goujon_sertir, entretoise, rivet
    filetage: str | None = None
    matiere: str | None = None
    prix_unitaire_eur: float
    qte_min: int = 1
    operation_id: str | None = None

    def __repr__(self) -> str:
        return f"ComposantPydantic(reference={self.reference!r})"


class TraitementPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nom: str
    prix: float
    unite: str  # m2 ou kg
    minimum_lot_eur: float = 0.0
    delai_jours: int = 0
    matieres_compatibles: str | None = "toutes"

    def __repr__(self) -> str:
        return f"TraitementPydantic(id={self.id!r})"


class ClientPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nom: str
    secteur: str | None = None
    marge_specifique: float | None = None
    ia_externe_autorisee: bool = False
    reutilisation_autorisee: bool = False
    duree_conservation_plans_jours: int = 90
    suppression_si_refus: bool = True

    def __repr__(self) -> str:
        return f"ClientPydantic(id={self.id!r})"


class BorneControlePydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    champ: str
    min: float
    max: float
    niveau: str  # alerte ou bloquant
    message: str

    def __repr__(self) -> str:
        return f"BorneControle(champ={self.champ!r}, niveau={self.niveau!r})"


class HistoriqueDevisPydantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    date: date
    client_id: str | None = None
    reference_piece: str
    designation: str
    matiere_id: str | None = None
    epaisseur_mm: float
    flan_l_mm: float
    flan_w_mm: float
    masse_kg: float
    longueur_coupe_mm: float
    nb_trois: int = 0  # NOTE: DB colonne "nb_trous", modèle "nb_trois" par compatibilité
    nb_plis: int = 0
    nb_composants: int = 0
    traitement_id: str | None = None
    quantite: int = 1
    cout_unitaire_eur: float
    prix_unitaire_eur: float
    statut: str  # accepte, refuse, en_attente

    def __repr__(self) -> str:
        return f"HistoriqueDevisPydantic(id={self.id!r})"


# ---------------------------------------------------------------------------
# Fonctions d'accès en lecture — retournent les modèles Pydantic ci-dessus
# ou None / [] pour identifiants inconnus.
# Convention : `session: Session` est le PREMIER paramètre.

# Correspondance type de traitement extrait (schema.piece) → identifiant du
# référentiel `traitements`. Partagée par faisabilite et calcul_prix.
TRAITEMENT_ID_PAR_TYPE: dict[str, str] = {
    "peinture": "PEINTURE_POUDRE",
    "thermolaquage": "PEINTURE_POUDRE",
    "cataphorese": "CATAPHORESE",
    "zingage": "ZINGAGE",
    "galvanisation": "GALVA_CHAUD",
    "anodisation": "ANODISATION",
    "passivation": "PASSIVATION",
}


def get_matiere(matiere_id: str, session: Session) -> MatierePydantic | None:
    """Retourner la matière par son identifiant, ou None si introuvable."""
    from generateur_devis.data.tables import Matiere as MatiereTable

    ligne = session.get(MatiereTable, matiere_id)
    if ligne is None:
        return None
    return MatierePydantic(
        id=ligne.id,
        famille=ligne.famille,
        nuance=ligne.nuance,
        norme=ligne.norme,
        densite_kg_dm3=ligne.densite_kg_dm3,
        prix_eur_kg=ligne.prix_eur_kg,
        date_maj=ligne.date_maj,
        fournisseur=ligne.fournisseur,
    )


def list_matieres(session: Session) -> list[MatierePydantic]:
    """Lister toutes les matières du référentiel (écrans, listes déroulantes)."""
    from generateur_devis.data.tables import Matiere as MatiereTable

    return [
        MatierePydantic(
            id=ligne.id,
            famille=ligne.famille,
            nuance=ligne.nuance,
            norme=ligne.norme,
            densite_kg_dm3=ligne.densite_kg_dm3,
            prix_eur_kg=ligne.prix_eur_kg,
            date_maj=ligne.date_maj,
            fournisseur=ligne.fournisseur,
        )
        for ligne in session.query(MatiereTable).order_by(MatiereTable.id).all()
    ]


def list_clients(session: Session) -> list[ClientPydantic]:
    """Lister tous les clients du référentiel (écrans, listes déroulantes)."""
    from generateur_devis.data.tables import Client as ClientTable

    return [
        ClientPydantic(
            id=ligne.id,
            nom=ligne.nom,
            secteur=ligne.secteur,
            marge_specifique=ligne.marge_specifique,
            ia_externe_autorisee=ligne.ia_externe_autorisee,
            reutilisation_autorisee=ligne.reutilisation_autorisee,
            duree_conservation_plans_jours=ligne.duree_conservation_plans_jours,
            suppression_si_refus=ligne.suppression_si_refus,
        )
        for ligne in session.query(ClientTable).order_by(ClientTable.nom).all()
    ]


def list_epaisseurs(matiere_id: str, session: Session) -> list[EpaisseurDispoPydantic]:
    """Lister toutes les épaisseurs dispo pour une matière donnée."""
    from generateur_devis.data.tables import EpaisseurDispo as EpaisseurTable

    lignes_db = (
        session.execute(
            session.query(EpaisseurTable).filter(EpaisseurTable.matiere_id == matiere_id).statement
        )
        .scalars()
        .all()
    )
    return [
        EpaisseurDispoPydantic(
            matiere_id=ligne.matiere_id,
            epaisseur_mm=ligne.epaisseur_mm,
            format_mm=ligne.format_mm,
            surcout_pct=ligne.surcout_pct,
            en_stock=ligne.en_stock,
        )
        for ligne in lignes_db
    ]


def get_poste(poste_id: str, session: Session) -> PostePydantic | None:
    """Retourner le poste par son identifiant, ou None si introuvable."""
    from generateur_devis.data.tables import Poste as PosteTable

    ligne = session.get(PosteTable, poste_id)
    if ligne is None:
        return None
    return PostePydantic(
        id=ligne.id,
        nom=ligne.nom,
        type=ligne.type,
        taux_horaire_eur_h=ligne.taux_horaire_eur_h,
        temps_reglage_min=ligne.temps_reglage_min,
    )


def get_vitesse_coupe(
    poste_id: str,
    famille: str,
    epaisseur_mm: float,
    session: Session,
) -> VitesseCoupePydantic | None:
    """Retourner la vitesse de coupe (poste + famille + épaisseur), ou None."""
    from generateur_devis.data.tables import VitesseCoupe as VitesseTable

    ligne = session.get(
        VitesseTable,
        (poste_id, famille, epaisseur_mm),
    )
    if ligne is None:
        return None
    return VitesseCoupePydantic(
        poste_id=ligne.poste_id,
        famille=ligne.famille,
        epaisseur_mm=ligne.epaisseur_mm,
        vitesse_m_min=ligne.vitesse_m_min,
        temps_amorcage_s=ligne.temps_amorcage_s,
        gaz=ligne.gaz,
    )


def get_temps_pliage(
    dimension_mm: float,
    epaisseur_mm: float,
    session: Session,
) -> TempsPliagePydantic | None:
    """Retourner la plus petite tranche couvrant la dimension ET l'épaisseur.

    On recherche parmi toutes les lignes où dim_max_mm >= dimension_mm
    ET epaisseur_max_mm >= epaisseur_mm, et on choisit celle dont la surface
    (dim_max_mm * epaisseur_max_mm) est la plus petite (proche appelant).
    Retourne None si aucune tranche ne couvre la demande.
    """
    from generateur_devis.data.tables import TempsPliage as TempsTable

    # Requête toutes les lignes de temps_pliage
    q = session.query(TempsTable)
    lignes_db = q.all()

    def _surface(cand) -> float:
        return float(cand.dim_max_mm * cand.epaisseur_max_mm)

    candidats = [
        c for c in lignes_db if c.dim_max_mm >= dimension_mm and c.epaisseur_max_mm >= epaisseur_mm
    ]
    if not candidats:
        return None

    best = min(candidats, key=_surface)

    return TempsPliagePydantic(
        categorie=best.categorie,
        dim_max_mm=best.dim_max_mm,
        epaisseur_max_mm=best.epaisseur_max_mm,
        temps_par_pli_s=best.temps_par_pli_s,
        temps_retournement_s=best.temps_retournement_s,
        nb_operateurs=best.nb_operateurs,
    )


def get_operation(operation_id: str, session: Session) -> OperationPydantic | None:
    """Retourner l'opération par son identifiant, ou None si introuvable."""
    from generateur_devis.data.tables import Operation as OperationTable

    ligne = session.get(OperationTable, operation_id)
    if ligne is None:
        return None
    return OperationPydantic(
        id=ligne.id,
        nom=ligne.nom,
        poste_id=ligne.poste_id,
        temps_s=ligne.temps_s,
        unite=ligne.unite,
    )


def get_composant(reference: str, session: Session) -> ComposantPydantic | None:
    """Retourner le composant par sa référence, ou None si introuvable."""
    from generateur_devis.data.tables import Composant as ComposantTable

    ligne = session.get(ComposantTable, reference)
    if ligne is None:
        return None
    return ComposantPydantic(
        reference=ligne.reference,
        designation=ligne.designation,
        type=ligne.type,
        filetage=ligne.filetage,
        matiere=ligne.matiere,
        prix_unitaire_eur=ligne.prix_unitaire_eur,
        qte_min=ligne.qte_min,
        operation_id=ligne.operation_id,
    )


def get_traitement(traitement_id: str, session: Session) -> TraitementPydantic | None:
    """Retourner le traitement par son identifiant, ou None si introuvable.

    NOTE : le paramètre s'appelle ``traitement_id`` et non ``id`` pour éviter
    de masquer le built-in Python ``id()``.
    """
    from generateur_devis.data.tables import Traitement as TraitementTable

    ligne = session.get(TraitementTable, traitement_id)
    if ligne is None:
        return None
    return TraitementPydantic(
        id=ligne.id,
        nom=ligne.nom,
        prix=ligne.prix,
        unite=ligne.unite,
        minimum_lot_eur=ligne.minimum_lot_eur,
        delai_jours=ligne.delai_jours,
        matieres_compatibles=ligne.matieres_compatibles,
    )


def get_parametre(cle: str, session: Session) -> str | float | int:
    """Retourner la valeur du paramètre global identifié par ``cle ''.

    Conversion TEXT → type Python selon la clé connue (8 clés seules) :

    - marge_defaut, rendement_calepinage, facteur_k  → float
    - regle_diam_trou_min_e, regle_aile_min_e,
      regle_rayon_min_e                              → float
    - minimum_commande_eur, validite_devis_jours,
      prix_matiere_max_age_jours                      → int
    - paliers_quantite                                → list[int]
    - devise, poste_decoupe, poste_pliage,
      operation_ebavurage, operation_taraudage          → str

    Si la clé est inconnue, lever ValueError.
    """
    from generateur_devis.data.tables import Parametre as ParametreTable

    ligne = session.get(ParametreTable, cle)
    if ligne is None:
        # La clé n'existe pas en base — c'est une erreur de configuration
        msg = f"Paramètre inconnu : {cle!r}"
        raise ValueError(msg)

    valeur_txt = ligne.valeur

    # Conversion selon la clé
    _conversion: dict[str, Any] = {
        "marge_defaut": float,
        "seuil_confiance_champs": float,
        "rendement_calepinage": float,
        "facteur_k": float,
        "regle_diam_trou_min_e": float,
        "regle_aile_min_e": float,
        "regle_rayon_min_e": float,
        "minimum_commande_eur": int,
        "frais_structure_pct": int,
        "validite_devis_jours": int,
        "prix_matiere_max_age_jours": int,
        "paliers_quantite": lambda v: [int(x.strip()) for x in v.split(",")],
        "devise": str,
        "poste_decoupe": str,
        "poste_pliage": str,
        "operation_ebavurage": str,
        "operation_taraudage": str,
        "conditions_generales": str,
        "modele_extraction": str,
        "rayon_pliage_defaut_mm": float,
    }

    if cle not in _conversion:
        msg = f"Clé de paramètre inconnue : {cle!r}"
        raise ValueError(msg)

    return _conversion[cle](valeur_txt)


def get_client(client_id: str, session: Session) -> ClientPydantic | None:
    """Retourner le client par son identifiant, ou None si introuvable."""
    from generateur_devis.data.tables import Client as ClientTable

    ligne = session.get(ClientTable, client_id)
    if ligne is None:
        return None
    return ClientPydantic(
        id=ligne.id,
        nom=ligne.nom,
        secteur=ligne.secteur,
        marge_specifique=ligne.marge_specifique,
        ia_externe_autorisee=ligne.ia_externe_autorisee,
        reutilisation_autorisee=ligne.reutilisation_autorisee,
        duree_conservation_plans_jours=ligne.duree_conservation_plans_jours,
        suppression_si_refus=ligne.suppression_si_refus,
    )


def get_bornes(session: Session) -> list[BorneControlePydantic]:
    """Retourner toutes les bornes de contrôle de la table ``bornes_controle``."""
    from generateur_devis.data.tables import BorneControle as BorneTable

    lignes_db = session.execute(session.query(BorneTable).statement).scalars().all()
    return [
        BorneControlePydantic(
            champ=ligne.champ,
            min=ligne.min,
            max=ligne.max,
            niveau=ligne.niveau,
            message=ligne.message,
        )
        for ligne in lignes_db
    ]


def list_historique_similaires(
    session: Session,
    matiere_id: str | None = None,
    traitement_id: str | None = None,
    quantite_min: int | None = None,
    quantite_max: int | None = None,
) -> list[HistoriqueDevisPydantic]:
    """Retourner l'historique de devis filtré selon les critères optionnels.

    Aucun critère → retour de toutes les lignes (liste vide si pas de données).
    Les filtres sont appliqués via des jointures SQL simples sur les FK.
    """
    from generateur_devis.data.tables import HistoriqueDevis as HistoriqueTable

    q = session.query(HistoriqueTable)

    if matiere_id is not None:
        q = q.filter(HistoriqueTable.matiere_id == matiere_id)
    if traitement_id is not None:
        q = q.filter(HistoriqueTable.traitement_id == traitement_id)
    if quantite_min is not None:
        q = q.filter(HistoriqueTable.quantite >= quantite_min)
    if quantite_max is not None:
        q = q.filter(HistoriqueTable.quantite <= quantite_max)

    lignes_db = q.all()
    return [
        HistoriqueDevisPydantic(
            id=ligne.id,
            date=ligne.date,
            client_id=ligne.client_id,
            reference_piece=ligne.reference_piece,
            designation=ligne.designation,
            matiere_id=ligne.matiere_id,
            epaisseur_mm=ligne.epaisseur_mm,
            flan_l_mm=ligne.flan_l_mm,
            flan_w_mm=ligne.flan_w_mm,
            masse_kg=ligne.masse_kg,
            longueur_coupe_mm=ligne.longueur_coupe_mm,
            nb_trois=ligne.nb_trous,  # DB: nb_trous ; modèle: nb_trois
            nb_plis=ligne.nb_plis,
            nb_composants=ligne.nb_composants,
            traitement_id=ligne.traitement_id,
            quantite=ligne.quantite,
            cout_unitaire_eur=ligne.cout_unitaire_eur,
            prix_unitaire_eur=ligne.prix_unitaire_eur,
            statut=ligne.statut,
        )
        for ligne in lignes_db
    ]
