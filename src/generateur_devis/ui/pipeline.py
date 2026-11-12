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
- document que l'IA signale comme non exploitable (règle 14 du prompt :
  devis, facture, page sans rapport) → aucune pièce, l'écran reste sur le
  dépôt (issue #64) ;
- plan coté en pouces → pièce convertie en mm juste après l'extraction,
  conversion tracée dans ``ResultatDevis.conversion`` (issue #57) ;
- ``memoire`` (dict partagé du serveur) : un plan déjà extrait avec succès
  par le même modèle est repris sans appel IA, ``extraction_reprise=True``
  (issue #68) ; rien n'est écrit sur disque ;
- composants non chiffrés ici : leur référence n'est pas extraite du plan
  (tranché en 3.2) ; ils sont rattachés au référentiel à l'écran de
  validation, qui les transmet à ``rechiffrer(..., composants=...)`` (#56).
"""

from __future__ import annotations

import tempfile
from collections.abc import MutableMapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.calcul_prix import Chiffrage, ErreurChiffrage, chiffrer
from generateur_devis.controles_prix import evaluer_controles_prix
from generateur_devis.data.acces import get_matiere, get_parametre
from generateur_devis.extraction import ResultatExtraction, charger_plan, extraire
from generateur_devis.extraction.prompt import ANOMALIE_DOCUMENT
from generateur_devis.faisabilite import Constat, evaluer_faisabilite
from generateur_devis.geometrie import ErreurGeometrie, Flan, construire_flan
from generateur_devis.llm import creer_modele
from generateur_devis.schema.piece import Anomalie, PieceExtraite
from generateur_devis.unites import ConversionUnites, convertir_en_mm


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
    conversion: ConversionUnites | None = None
    """Unité d'origine et valeurs converties en mm (issue #57) ; None si l'extraction
    a échoué ou depuis ``rechiffrer`` (la pièce y est déjà en mm)."""
    extraction_reprise: bool = False
    """Extraction reprise de la mémoire du serveur (même plan, même modèle) : aucun
    appel IA (issue #68)."""

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


def anomalie_document(piece: PieceExtraite) -> Anomalie | None:
    """Première anomalie « document non exploitable » signalée par l'IA (règle 14), sinon None.

    Critère : ``type == "illisible"`` et ``champ == ANOMALIE_DOCUMENT``. Une
    anomalie « illisible » sur un autre champ (ou ``champ=None``) ne rejette
    pas le plan.
    """
    return next(
        (a for a in piece.anomalies if a.type == "illisible" and a.champ == ANOMALIE_DOCUMENT),
        None,
    )


def orchestrer_devis(
    plan: bytes,
    nom_fichier: str,
    client_id: str | None,
    quantites: list[int] | None,
    matiere_id: str | None,
    nom_modele: str,
    session: Session,
    memoire: MutableMapping[str, ResultatExtraction] | None = None,
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
        memoire: extractions réussies déjà faites (``extraire(memoire=...)``) ;
            None = toujours un appel IA.

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

    extraction = extraire(document, creer_modele(nom_modele), memoire=memoire)
    if extraction.erreur is not None or extraction.piece is None:
        return ResultatDevis(
            erreur=f"Extraction impossible : {extraction.erreur or 'aucune pièce extraite.'}"
        )
    # Document qui n'est pas un plan (devis, facture…) : refus avant matière et
    # conversion, même si une matière est choisie au dépôt (issue #64).
    anomalie = anomalie_document(extraction.piece)
    if anomalie is not None:
        return ResultatDevis(
            erreur=(
                f"Ce document n'est pas un plan exploitable : {anomalie.description} "
                "Déposez le plan de la pièce (PDF ou image)."
            )
        )
    # Plan en pouces → mm, ici et pas dans extraire() : l'évaluation compare la
    # sortie brute, dans l'unité du plan (issue #57). Avant matière, géométrie,
    # faisabilité et chiffrage, qui travaillent tous en mm.
    # La pièce servie est une copie : l'entrée en mémoire reste dans l'unité du plan.
    piece, conversion = convertir_en_mm(extraction.piece)
    suite = {"conversion": conversion, "extraction_reprise": extraction.depuis_cache}

    try:
        matiere = _resoudre_matiere(piece, matiere_id, session)
    except ErreurPipeline as e:
        return ResultatDevis(piece=piece, erreur=str(e), **suite)
    if matiere is None:
        return ResultatDevis(piece=piece, matiere_id=None, erreur=None, **suite)

    resultat = rechiffrer(piece, matiere, client_id, quantites, session)
    return resultat.model_copy(update=suite)


def rechiffrer(
    piece: PieceExtraite,
    matiere_id: str,
    client_id: str | None,
    quantites: list[int] | None,
    session: Session,
    composants: list[tuple[str, int]] | None = None,
) -> ResultatDevis:
    """Rechiffre une pièce modifiée sans repasser par l'extraction (issue #24).

    ``composants`` : couples (référence du référentiel, quantité) rattachés à
    l'écran de validation (issue #56), transmis tels quels à ``chiffrer``.

    Étapes géométrie → faisabilité → chiffrage → contrôles, déterministes et
    sans appel IA : appelée à chaque modification du formulaire de validation
    (moins d'une seconde, architecture §4). Mêmes règles que le pipeline :
    blocage faisabilité → pas de chiffrage ; erreurs métier → ``erreur``
    lisible.
    """
    matiere_ref = get_matiere(matiere_id, session)
    if matiere_ref is None:
        return ResultatDevis(
            piece=piece, matiere_id=matiere_id, erreur=f"Matière inconnue : {matiere_id}."
        )
    facteur_k = float(get_parametre("facteur_k", session))
    try:
        flan = construire_flan(piece, matiere_ref.densite_kg_dm3, facteur_k)
    except ErreurGeometrie as e:
        return ResultatDevis(piece=piece, matiere_id=matiere_id, erreur=str(e))

    constats = evaluer_faisabilite(piece, matiere_id, session)
    resultat = ResultatDevis(piece=piece, flan=flan, matiere_id=matiere_id, constats=constats)
    if resultat.bloque:
        return resultat

    try:
        resultat.chiffrage = chiffrer(
            piece,
            matiere_id,
            session,
            quantites=quantites,
            composants=composants,
            client_id=client_id,
        )
    except ErreurChiffrage as e:
        resultat.erreur = str(e)
        return resultat
    resultat.alertes_controles = evaluer_controles_prix(
        resultat.chiffrage, piece, flan, matiere_id, session
    )
    return resultat
