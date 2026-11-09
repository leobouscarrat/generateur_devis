"""Déclarations des tables SQLAlchemy (Python 3.12 / SQLAlchemy 2.0)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Table des matières
# ---------------------------------------------------------------------------

class Matiere(Base):
    __tablename__ = "matieres"

    id: Mapped[str] = mapped_column(primary_key=True)
    famille: Mapped[str] = mapped_column(nullable=False, default="acier")
    nuance: Mapped[str] = mapped_column(nullable=True)
    norme: Mapped[str] = mapped_column(nullable=True)
    densite_kg_dm3: Mapped[float] = mapped_column(nullable=False, default=7.85)
    prix_eur_kg: Mapped[float] = mapped_column(nullable=False, default=1.10)
    date_maj: Mapped[date] = mapped_column(nullable=False, default=date.today)
    fournisseur: Mapped[str] = mapped_column(nullable=True, default="Fournisseur fictif")

    def __repr__(self) -> str:
        return f"Matiere(id={self.id!r}, famille={self.famille!r})"


# ---------------------------------------------------------------------------
# Table des épaisseurs disponibles par matière
# ---------------------------------------------------------------------------

class EpaisseurDispo(Base):
    __tablename__ = "epaisseurs_dispo"

    matiere_id: Mapped[str] = mapped_column(
        ForeignKey("matieres.id", ondelete="CASCADE"), primary_key=True
    )
    epaisseur_mm: Mapped[float] = mapped_column(nullable=False)
    format_mm: Mapped[str] = mapped_column(nullable=True, default="3000 × 1500")
    surcout_pct: Mapped[float] = mapped_column(nullable=False, default=0.0)
    en_stock: Mapped[bool] = mapped_column(nullable=False, default=True)

    def __repr__(self) -> str:
        return f"EpaisseurDispo(matiere_id={self.matiere_id!r}, epaisseur_mm={self.epaisseur_mm!r})"


# ---------------------------------------------------------------------------
# Table des postes machine
# ---------------------------------------------------------------------------

class Poste(Base):
    __tablename__ = "postes"

    id: Mapped[str] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(
        nullable=False,
    )  # decoupe, pliage, soudure, sertissage, manuel
    taux_horaire_eur_h: Mapped[float] = mapped_column(nullable=False)
    temps_reglage_min: Mapped[float] = mapped_column(nullable=False, default=15.0)

    def __repr__(self) -> str:
        return f"Poste(id={self.id!r}, nom={self.nom!r})"


# ---------------------------------------------------------------------------
# Table des vitesses de coupe
# ---------------------------------------------------------------------------

class VitesseCoupe(Base):
    __tablename__ = "vitesses_coupe"

    poste_id: Mapped[str] = mapped_column(
        ForeignKey("postes.id", ondelete="CASCADE"), primary_key=True
    )
    famille: Mapped[str] = mapped_column(nullable=False, primary_key=True)
    epaisseur_mm: Mapped[float] = mapped_column(nullable=False, primary_key=True)
    vitesse_m_min: Mapped[float] = mapped_column(nullable=False)
    temps_amorcage_s: Mapped[float] = mapped_column(nullable=False, default=0.7)
    gaz: Mapped[str] = mapped_column(nullable=True, default="O2")

    def __repr__(self) -> str:
        return f"VitesseCoupe(poste_id={self.poste_id!r}, famille={self.famille!r}, epaisseur_mm={self.epaisseur_mm!r})"


# ---------------------------------------------------------------------------
# Table des temps de pliage
# ---------------------------------------------------------------------------

class TempsPliage(Base):
    __tablename__ = "temps_pliage"

    categorie: Mapped[str] = mapped_column(nullable=False, primary_key=True)
    dim_max_mm: Mapped[int] = mapped_column(nullable=False, primary_key=True)
    epaisseur_max_mm: Mapped[float] = mapped_column(nullable=False, primary_key=True)
    temps_par_pli_s: Mapped[float] = mapped_column(nullable=False)
    temps_retournement_s: Mapped[float] = mapped_column(nullable=False, default=0.0)
    nb_operateurs: Mapped[int] = mapped_column(nullable=False, default=1)

    def __repr__(self) -> str:
        return f"TempsPliage(categorie={self.categorie!r}, dim_max_mm={self.dim_max_mm!r}, epaisseur_max_mm={self.epaisseur_max_mm!r})"


# ---------------------------------------------------------------------------
# Table des opérations standards
# ---------------------------------------------------------------------------

class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    poste_id: Mapped[str] = mapped_column(
        ForeignKey("postes.id", ondelete="SET NULL"), nullable=True
    )
    temps_s: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(
        nullable=False,
    )  # par mètre, par trou, par pièce

    def __repr__(self) -> str:
        return f"Operation(id={self.id!r}, nom={self.nom!r})"


# ---------------------------------------------------------------------------
# Table des composants achetés
# ---------------------------------------------------------------------------

class Composant(Base):
    __tablename__ = "composants"

    reference: Mapped[str] = mapped_column(primary_key=True)
    designation: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(nullable=False)  # ecrou_sertir, goujon_sertir, entretoise, rivet
    filetage: Mapped[str] = mapped_column(nullable=True)
    matiere: Mapped[str] = mapped_column(nullable=True)
    prix_unitaire_eur: Mapped[float] = mapped_column(nullable=False)
    qte_min: Mapped[int] = mapped_column(nullable=False, default=1)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operations.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"Composant(reference={self.reference!r})"


# ---------------------------------------------------------------------------
# Table des traitements de surface
# ---------------------------------------------------------------------------

class Traitement(Base):
    __tablename__ = "traitements"

    id: Mapped[str] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    prix: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(nullable=False)  # m2 ou kg
    minimum_lot_eur: Mapped[float] = mapped_column(nullable=False, default=0.0)
    delai_jours: Mapped[int] = mapped_column(nullable=False, default=0)
    matieres_compatibles: Mapped[str] = mapped_column(
        nullable=True
    )  # acier, inox, aluminium, toutes

    def __repr__(self) -> str:
        return f"Traitement(id={self.id!r}, nom={self.nom!r})"


# ---------------------------------------------------------------------------
# Table des paramètres globaux
# ---------------------------------------------------------------------------

class Parametre(Base):
    __tablename__ = "parametres"

    cle: Mapped[str] = mapped_column(primary_key=True)
    valeur: Mapped[float] = mapped_column(nullable=False)
    unite: Mapped[str] = mapped_column(nullable=True, default=None)
    description: Mapped[str] = mapped_column(nullable=True, default=None)

    def __repr__(self) -> str:
        return f"Parametre(cle={self.cle!r}, valeur={self.valeur!r})"


# ---------------------------------------------------------------------------
# Table des clients
# ---------------------------------------------------------------------------

class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    secteur: Mapped[str] = mapped_column(nullable=True)
    marge_specifique: Mapped[float] = mapped_column(
        nullable=True, default=None
    )
    ia_externe_autorisee: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    reutilisation_autorisee: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    duree_conservation_plans_jours: Mapped[int] = mapped_column(
        nullable=False, default=90
    )
    suppression_si_refus: Mapped[bool] = mapped_column(
        nullable=False, default=True
    )

    def __repr__(self) -> str:
        return f"Client(id={self.id!r}, nom={self.nom!r})"


# ---------------------------------------------------------------------------
# Table de l'historique des devis
# ---------------------------------------------------------------------------

class HistoriqueDevis(Base):
    __tablename__ = "historique_devis"

    id: Mapped[str] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(nullable=False)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    reference_piece: Mapped[str] = mapped_column(nullable=False)
    designation: Mapped[str] = mapped_column(nullable=False)
    matiere_id: Mapped[str] = mapped_column(
        ForeignKey("matieres.id", ondelete="SET NULL"), nullable=True
    )
    epaisseur_mm: Mapped[float] = mapped_column(nullable=False)
    flan_l_mm: Mapped[float] = mapped_column(nullable=False)
    flan_w_mm: Mapped[float] = mapped_column(nullable=False)
    masse_kg: Mapped[float] = mapped_column(nullable=False)
    longueur_coupe_mm: Mapped[float] = mapped_column(nullable=False)
    nb_trous: Mapped[int] = mapped_column(nullable=False, default=0)
    nb_plis: Mapped[int] = mapped_column(nullable=False, default=0)
    nb_composants: Mapped[int] = mapped_column(nullable=False, default=0)
    traitement_id: Mapped[str] = mapped_column(
        ForeignKey("traitements.id", ondelete="SET NULL"), nullable=True
    )
    quantite: Mapped[int] = mapped_column(nullable=False, default=1)
    cout_unitaire_eur: Mapped[float] = mapped_column(nullable=False)
    prix_unitaire_eur: Mapped[float] = mapped_column(nullable=False)
    statut: Mapped[str] = mapped_column(
        nullable=False
    )  # accepte, refuse, en_attente

    def __repr__(self) -> str:
        return f"HistoriqueDevis(id={self.id!r}, date={self.date!r})"


# ---------------------------------------------------------------------------
# Table des bornes de contrôle du chiffrage
# ---------------------------------------------------------------------------


class BorneControle(Base):
    __tablename__ = "bornes_controle"

    champ: Mapped[str] = mapped_column(primary_key=True)
    min: Mapped[float] = mapped_column(nullable=False)
    max: Mapped[float] = mapped_column(nullable=False)
    niveau: Mapped[str] = mapped_column(nullable=False)  # alerte ou bloquant
    message: Mapped[str] = mapped_column(nullable=False)

    def __repr__(self) -> str:
        return f"BorneControle(champ={self.champ!r}, niveau={self.niveau!r})"
