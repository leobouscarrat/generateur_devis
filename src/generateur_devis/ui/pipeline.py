"""Pipeline d'orchestration du parcours devis (issue #23, architecture §13).

Fonction **pure** (aucun import Streamlit) qui enchaîne les étapes 1 à 5 du
parcours : extraction du plan → géométrie → faisabilité → chiffrage
provisoire → contrôles de cohérence. L'écran Streamlit ne fait que
présenter le `ResultatDevis` ; tout est testable avec pytest.

Conventions :
- entrée = **bytes** du plan + nom de fichier (UploadedFile.read()) ; le
  pipeline écrit un fichier temporaire, seule entrée de ``charger_plan`` ;
- le modèle d'extraction est passé par désignation (``llm.creer_modele``) —
  aucune valeur en dur dans le pipeline ;
- matière absente du plan (et non fournie) → résultat **partiel sans
  chiffrage**, à compléter à la validation (4.3) ;
- blocage faisabilité → chiffrage non calculé (les constats suffisent) ;
- composants non chiffrés ici : leur référence n'est pas extraite du plan
  (tranché en 3.2), ils seront saisis à la validation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.calcul_prix import Chiffrage, ErreurChiffrage, chiffrer
from generateur_devis.controles_prix import evaluer_controles_prix
from generateur_devis.data.acces import get_matiere, get_parametre
from generateur_devis.extraction import charger_plan, extraire
from generateur_devis.faisabilite import Constat, evaluer_faisabilite
from generateur_devis.geometrie import ErreurGeometrie, Flan, construire_flan
from generateur_devis.llm import creer_modele
from generateur_devis.schema.piece import PieceExtraite


class ErreurPipeline(Exception):
    """Échec d'une étape du pipeline (message lisible, destiné à l'écran)."""


class ResultatDevis(BaseModel):
    """Résultat complet (ou partiel) du pipeline — transmis à l'écran 4.3."""

    model_config = ConfigDict(extra="forbid")

    piece: PieceExtraite | None = None
    flan: Flan | None = None
    matiere_id: str | None = None
    """Matière retenue pour la suite (fournie ou résolue depuis le plan)."""
    constats: list[Constat] = []
    """Constats de faisabilité (alertes et blocages)."""
    chiffrage: Chiffrage | None = None
    alertes_controles: list[Constat] = []
    erreur: str | None = None
    """Échec d'une étape (extraction illisible, géométrie impossible…)."""

    @property
    def bloque(self) -> bool:
        return any(c.severite == "blocage" for c in self.constats)


def _resoudre_matiere(piece: PieceExtraite, matiere_id: str | None, session: Session) -> str | None:
    """Matière fournie, sinon désignation extraite du plan si elle existe en base."""
    if matiere_id is not None:
        if get_matiere(matiere_id, session) is None:
            msg = f"Matière inconnue : {matiere_id}."
            raise ErreurPipeline(msg)
        return matiere_id
    designation = piece.matiere.designation.valeur
    if designation and get_matiere(designation, session) is not None:
        return designation
    return None


def orchestrer_devis(
    plan: bytes,
    nom_fichier: str,
    client_id: str | None,
    quantites: list[int] | None,
    matiere_id: str | None,
    nom_modele: str,
    session: Session,
) -> ResultatDevis:
    """Exécute le parcours extraction → chiffrage provisoire sur un plan.

    Args:
        plan: contenu du plan (PDF ou image), ex. ``UploadedFile.read()``.
        nom_fichier: nom d'origine (l'extension détermine le format).
        client_id: client du contexte commercial (marge spécifique éventuelle).
        quantites: quantités du contexte ; défaut = paliers du paramètre
            ``paliers_quantite``.
        matiere_id: matière choisie ; sinon résolue depuis le plan.
        nom_modele: désignation du modèle d'extraction (``llm.creer_modele``).
        session: session SQLAlchemy sur la base de référence.

    Returns:
        Le `ResultatDevis`, complet ou partiel (voir docstring du module).
    """
    suffixe = Path(nom_fichier).suffix
    try:
        with tempfile.NamedTemporaryFile(suffix=suffixe, delete=False) as tmp:
            tmp.write(plan)
            chemin = Path(tmp.name)
        try:
            document = charger_plan(chemin)
        finally:
            chemin.unlink(missing_ok=True)
    except ValueError as e:
        return ResultatDevis(erreur=str(e))

    extraction = extraire(document, creer_modele(nom_modele))
    if extraction.erreur is not None or extraction.piece is None:
        return ResultatDevis(
            erreur=f"Extraction impossible : {extraction.erreur or 'aucune pièce extraite.'}"
        )
    piece = extraction.piece

    try:
        matiere = _resoudre_matiere(piece, matiere_id, session)
    except ErreurPipeline as e:
        return ResultatDevis(piece=piece, erreur=str(e))

    # --- Géométrie + faisabilité (dès que l'épaisseur est connue) ----------
    if matiere is None:
        return ResultatDevis(piece=piece, matiere_id=None, erreur=None)
    matiere_ref = get_matiere(matiere, session)
    assert matiere_ref is not None  # garanti par _resoudre_matiere
    facteur_k = float(get_parametre("facteur_k", session))
    try:
        flan = construire_flan(piece, matiere_ref.densite_kg_dm3, facteur_k)
    except ErreurGeometrie as e:
        return ResultatDevis(piece=piece, matiere_id=matiere, erreur=str(e))

    constats = evaluer_faisabilite(piece, matiere, session)
    resultat = ResultatDevis(piece=piece, flan=flan, matiere_id=matiere, constats=constats)
    if resultat.bloque:
        return resultat

    # --- Chiffrage provisoire + contrôles -----------------------------------
    try:
        resultat.chiffrage = chiffrer(
            piece, matiere, session, quantites=quantites, client_id=client_id
        )
    except ErreurChiffrage as e:
        resultat.erreur = str(e)
        return resultat
    resultat.alertes_controles = evaluer_controles_prix(
        resultat.chiffrage, piece, flan, matiere, session
    )
    return resultat
