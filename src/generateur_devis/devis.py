"""Cycle de vie d'un devis (issue #22) : figeage, modifications, émission.

Un `Devis` embarque le `Chiffrage` complet (3.3) tel quel : **figeage = ne
jamais recalculer** — une fois validé, le devis ne change plus si un prix
de référence évolue ensuite (architecture §Étape 5). La marge reste
modifiable après validation : les prix sont alors **rechiffrés depuis les
coûts figés** (`prix = coût ÷ (1 − marge)`), sans aucune relecture des
référentiels.

Persistance V1 : sérialisation JSON (`model_dump_json` / round-trip) —
aucune table ni migration nouvelle. À l'émission, le devis est converti en
ligne de la table existante `historique_devis` (§Étape 6).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.calcul_prix import BlocFinition, Chiffrage
from generateur_devis.data.tables import HistoriqueDevis
from generateur_devis.geometrie import Flan
from generateur_devis.schema.piece import PieceExtraite

StatutDevis = Literal["brouillon", "valide", "emis"]


class ErreurDevis(Exception):
    """Transition d'état ou modification interdite sur un devis."""


class Modification(BaseModel):
    """Une modification du devis, enregistrée avec son auteur."""

    model_config = ConfigDict(extra="forbid")

    auteur: str
    date: datetime
    champ: str
    """Champ modifié, ex. ``marge``, ``quantite_commandee``, ``options``."""
    avant: str | float | int | None
    apres: str | float | int | None


class Devis(BaseModel):
    """Un devis : pièce validée + chiffrage figé + cycle de vie."""

    model_config = ConfigDict(extra="forbid")

    id: str
    client_id: str | None = None
    matiere_id: str
    piece_validee: PieceExtraite
    chiffrage: Chiffrage
    marge: float
    options: list[BlocFinition] = []
    """Options chiffrées à part (V1 : finition, ex. peinture proposée)."""
    quantite_commandee: int
    """Quantité retenue pour l'émission (palier de référence historique)."""
    statut: StatutDevis = "brouillon"
    auteur: str | None = None
    date_creation: datetime
    modifications: list[Modification] = []
    date_emission: datetime | None = None

    def palier_commande(self):
        """Le palier à la quantité commandée (ErreurDevis si absent)."""
        for palier in self.chiffrage.paliers:
            if palier.quantite == self.quantite_commandee:
                return palier
        msg = f"Aucun palier à la quantité commandée {self.quantite_commandee}."
        raise ErreurDevis(msg)

    def _verrouiller_si_emis(self) -> None:
        if self.statut == "emis":
            msg = f"Le devis {self.id} est émis : plus modifiable."
            raise ErreurDevis(msg)

    def _journaliser(self, auteur: str, champ: str, avant: Any, apres: Any) -> None:
        self.modifications.append(
            Modification(auteur=auteur, date=datetime.now(), champ=champ, avant=avant, apres=apres)
        )
        self.auteur = auteur

    def valider(self, auteur: str) -> None:
        """Brouillon → validé : fige le chiffrage (plus de recalcul)."""
        self._verrouiller_si_emis()
        if self.statut == "valide":
            return
        self._journaliser(auteur, "statut", self.statut, "valide")
        self.statut = "valide"

    def changer_marge(self, auteur: str, marge: float) -> None:
        """Modifie la marge et rechiffre les prix depuis les coûts figés.

        Les coûts ne changent pas ; seuls les prix unitaires sont
        recalculés (`prix = coût ÷ (1 − marge)`) — sans relecture des
        tables de référence.
        """
        self._verrouiller_si_emis()
        if not 0 <= marge < 1:
            msg = f"Marge invalide : {marge}."
            raise ErreurDevis(msg)
        self._journaliser(auteur, "marge", self.marge, marge)
        self.marge = marge
        for palier in self.chiffrage.paliers:
            palier.prix_unitaire_eur = palier.cout_unitaire_eur / (1.0 - marge)


def emettre(devis: Devis, flan: Flan, auteur: str, session: Session) -> HistoriqueDevis:
    """Émet le devis : statut « emis » + ligne `historique_devis`.

    Args:
        devis: devis validé (la validation est un prérequis de l'émission).
        flan: flan de la pièce (dimensions de la ligne historique) — les
            mesures géométriques sont déterministes, seuls les prix sont
            figés ; le flan est fourni par l'appelant.
        auteur: auteur de l'émission.
        session: session SQLAlchemy (la ligne est ajoutée, non commitée).

    Returns:
        La ligne `historique_devis` créée.

    Raises:
        ErreurDevis: devis non validé, déjà émis, ou palier à la quantité
            commandée absent.
    """
    devis._verrouiller_si_emis()
    if devis.statut != "valide":
        msg = f"Le devis {devis.id} doit être validé avant émission (statut {devis.statut!r})."
        raise ErreurDevis(msg)
    palier = devis.palier_commande()
    piece = devis.piece_validee
    nb_plis = piece.profil_pliage.nb_plis if piece.profil_pliage else 0
    nb_trous = sum(t.quantite for t in piece.contours.trous)
    nb_composants = sum(c.quantite for c in piece.composants)
    traitement_id = devis.options[0].traitement_id if devis.options else None

    ligne = HistoriqueDevis(
        id=devis.id,
        date=date.today(),
        client_id=devis.client_id,
        reference_piece=piece.identification.reference.valeur or devis.id,
        designation=piece.identification.designation.valeur or "Pièce sans désignation",
        matiere_id=devis.matiere_id,
        epaisseur_mm=flan.epaisseur_mm,
        flan_l_mm=flan.longueur_developpee_mm,
        flan_w_mm=flan.largeur_mm,
        masse_kg=flan.masse_flan_kg,
        longueur_coupe_mm=flan.longueur_coupe_mm,
        nb_trous=nb_trous,
        nb_plis=nb_plis,
        nb_composants=nb_composants,
        traitement_id=traitement_id,
        quantite=devis.quantite_commandee,
        cout_unitaire_eur=palier.cout_unitaire_eur,
        prix_unitaire_eur=palier.prix_unitaire_eur,
        statut="en_attente",
    )
    session.add(ligne)
    devis.statut = "emis"
    devis.date_emission = datetime.now()
    devis._journaliser(auteur, "statut", "valide", "emis")
    return ligne
