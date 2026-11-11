"""Moteur de calcul des coûts — blocs 1 à 6.

Blocs 1 à 3 (issue #13) : matière, découpe, pliage.
Blocs 4 à 6 (issue #14) : soudure (0 en V1), finition (option avec minimum
de lot), composants achetés & opérations secondaires.

Chiffrage déterministe d'une pièce de tôlerie, à partir de sa géométrie
(``geometrie.construire_flan``, issue #7) et des référentiels en base lus via
``data/acces.py`` : **aucune valeur en dur** (prix matière, rendement de
calepinage, vitesses de coupe, temps de pliage, taux horaires et réglages
viennent tous des tables).

Formules : docs/logique_metier.md §3 (blocs 1–3). Chaque bloc sépare :

- le **coût variable unitaire** (payé à la pièce) ;
- le **coût fixe de lot** (réglages, payé une fois par lot) — prérequis des
  paliers de quantité (§5), agrégés en 3.3 (#15).

Limites V1 assumées :

- le temps de retournement de la presse plieuse (``temps_retournement_s`` de
  la table ``temps_pliage``) n'est **pas** compté : la référence piece_support
  (§8.3 : 2 plis × 8 s = 16 s) l'exclut ;
- le calepinage est approximé par un rendement fixe (§10).
"""

from __future__ import annotations

from datetime import date
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from generateur_devis.data.acces import (
    TRAITEMENT_ID_PAR_TYPE,
    get_client,
    get_composant,
    get_matiere,
    get_operation,
    get_parametre,
    get_poste,
    get_temps_pliage,
    get_traitement,
    get_vitesse_coupe,
)
from generateur_devis.faisabilite import evaluer_faisabilite
from generateur_devis.geometrie import Flan, construire_flan
from generateur_devis.schema.piece import PieceExtraite


class ErreurChiffrage(Exception):
    """Donnée de référence manquante ou invalide pour le chiffrage."""


class BlocMatiere(BaseModel):
    """Bloc 1 — matière (tôle consommée, chutes incluses)."""

    model_config = ConfigDict(extra="forbid")

    masse_flan_kg: float
    rendement_calepinage: float
    prix_matiere_eur_kg: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float = 0.0


class BlocDecoupe(BaseModel):
    """Bloc 2 — découpe laser (contour extérieur + contours intérieurs)."""

    model_config = ConfigDict(extra="forbid")

    longueur_coupe_mm: float
    nombre_amorcages: int
    vitesse_m_min: float
    temps_amorcage_s: float
    temps_cycle_s: float
    taux_horaire_eur_h: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocPliage(BaseModel):
    """Bloc 3 — pliage (nb plis × temps par pli, sans retournement en V1)."""

    model_config = ConfigDict(extra="forbid")

    nb_plis: int
    temps_par_pli_s: float
    temps_cycle_s: float
    taux_horaire_eur_h: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocsCout(BaseModel):
    """Les trois premiers blocs de coût d'une pièce."""

    model_config = ConfigDict(extra="forbid")

    matiere: BlocMatiere
    decoupe: BlocDecoupe
    pliage: BlocPliage


def calculer_bloc_matiere(flan: Flan, matiere_id: str, session: Session) -> BlocMatiere:
    """Bloc 1 : coût = masse flan ÷ rendement calepinage × prix matière.

    La masse du flan (rectangle englobant, trous et chanfreins en chute)
    est celle calculée par ``geometrie.construire_flan`` (§2.2).

    Raises:
        ErreurChiffrage: matière inconnue du référentiel ou rendement
            de calepinage nul.
    """
    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurChiffrage(msg)
    rendement = float(get_parametre("rendement_calepinage", session))
    if rendement <= 0:
        msg = f"Rendement de calepinage invalide : {rendement}."
        raise ErreurChiffrage(msg)
    cout = flan.masse_flan_kg / rendement * matiere.prix_eur_kg
    return BlocMatiere(
        masse_flan_kg=flan.masse_flan_kg,
        rendement_calepinage=rendement,
        prix_matiere_eur_kg=matiere.prix_eur_kg,
        cout_variable_eur=cout,
    )


def calculer_bloc_decoupe(flan: Flan, famille_matiere: str, session: Session) -> BlocDecoupe:
    """Bloc 2 : temps = longueur ÷ vitesse + amorçages ; coût × taux laser.

    La vitesse de coupe vient de la table ``vitesses_coupe`` (poste × famille
    × épaisseur) ; le réglage/programmation du poste est un coût fixe de lot.

    Raises:
        ErreurChiffrage: poste de découpe inconnu, ou pas de vitesse de
            coupe pour la famille × épaisseur.
    """
    poste_id = str(get_parametre("poste_decoupe", session))
    poste = get_poste(poste_id, session)
    if poste is None:
        msg = f"Poste de découpe inconnu dans le référentiel : {poste_id!r}."
        raise ErreurChiffrage(msg)
    vitesse = get_vitesse_coupe(poste_id, famille_matiere, flan.epaisseur_mm, session)
    if vitesse is None:
        msg = (
            f"Pas de vitesse de coupe pour {poste_id!r}, famille "
            f"{famille_matiere!r}, épaisseur {flan.epaisseur_mm} mm."
        )
        raise ErreurChiffrage(msg)
    temps_s = (
        flan.longueur_coupe_mm / 1000.0 / vitesse.vitesse_m_min * 60.0
        + flan.nombre_amorcages * vitesse.temps_amorcage_s
    )
    taux = poste.taux_horaire_eur_h
    return BlocDecoupe(
        longueur_coupe_mm=flan.longueur_coupe_mm,
        nombre_amorcages=flan.nombre_amorcages,
        vitesse_m_min=vitesse.vitesse_m_min,
        temps_amorcage_s=vitesse.temps_amorcage_s,
        temps_cycle_s=temps_s,
        taux_horaire_eur_h=taux,
        cout_variable_eur=temps_s / 3600.0 * taux,
        cout_fixe_eur_par_lot=poste.temps_reglage_min / 60.0 * taux,
    )


def calculer_bloc_pliage(piece: PieceExtraite, flan: Flan, session: Session) -> BlocPliage:
    """Bloc 3 : temps = nb plis × temps par pli (tranche ``temps_pliage``).

    La tranche est choisie par la dimension de la pièce (longueur de pli =
    largeur d'extrusion du flan) et l'épaisseur. Le réglage de la plieuse
    est un coût fixe de lot. Une pièce sans pli donne un bloc à zéro.

    Raises:
        ErreurChiffrage: poste de pliage inconnu, ou aucune tranche de
            temps de pliage ne couvrant la pièce (si elle a des plis).
    """
    nb_plis = piece.profil_pliage.nb_plis if piece.profil_pliage else 0
    poste_id = str(get_parametre("poste_pliage", session))
    poste = get_poste(poste_id, session)
    if poste is None:
        msg = f"Poste de pliage inconnu dans le référentiel : {poste_id!r}."
        raise ErreurChiffrage(msg)
    taux = poste.taux_horaire_eur_h
    if nb_plis == 0:
        return BlocPliage(
            nb_plis=0,
            temps_par_pli_s=0.0,
            temps_cycle_s=0.0,
            taux_horaire_eur_h=taux,
            cout_variable_eur=0.0,
            cout_fixe_eur_par_lot=0.0,
        )
    tranche = get_temps_pliage(flan.largeur_mm, flan.epaisseur_mm, session)
    if tranche is None:
        msg = (
            f"Aucune tranche de temps de pliage ne couvre {flan.largeur_mm} mm "
            f"× {flan.epaisseur_mm} mm."
        )
        raise ErreurChiffrage(msg)
    temps_s = nb_plis * tranche.temps_par_pli_s
    return BlocPliage(
        nb_plis=nb_plis,
        temps_par_pli_s=tranche.temps_par_pli_s,
        temps_cycle_s=temps_s,
        taux_horaire_eur_h=taux,
        cout_variable_eur=temps_s / 3600.0 * taux,
        cout_fixe_eur_par_lot=poste.temps_reglage_min / 60.0 * taux,
    )


def calculer_blocs_1_3(
    piece: PieceExtraite, flan: Flan, matiere_id: str, session: Session
) -> BlocsCout:
    """Calcule les blocs 1 à 3 du chiffrage (matière, découpe, pliage).

    Args:
        piece: pièce extraite du plan (schéma ``piece.py``).
        flan: flan construit par ``geometrie.construire_flan`` — ses mesures
            (masse, longueur de coupe, amorçages) sont consommées telles
            quelles, jamais recalculées.
        matiere_id: matière retenue pour le chiffrage (référentiel).
        session: session SQLAlchemy sur la base de référence.

    Returns:
        Les trois blocs, chacun avec ses grandeurs intermédiaires et la
        séparation coût variable unitaire / coût fixe de lot.
    """
    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurChiffrage(msg)
    return BlocsCout(
        matiere=calculer_bloc_matiere(flan, matiere_id, session),
        decoupe=calculer_bloc_decoupe(flan, matiere.famille, session),
        pliage=calculer_bloc_pliage(piece, flan, session),
    )


# ---------------------------------------------------------------------------
# Blocs 4 à 6 (issue #14) : soudure, finition, composants & op. secondaires
# ---------------------------------------------------------------------------


class BlocSoudure(BaseModel):
    """Bloc 4 — soudure / assemblage (0 pour une pièce unique en V1)."""

    model_config = ConfigDict(extra="forbid")

    cout_variable_eur: float = 0.0
    cout_fixe_eur_par_lot: float = 0.0


class BlocFinition(BaseModel):
    """Bloc 5 — finition / traitement de surface.

    Le minimum de lot ne rentre pas dans le moule variable + fixe ÷ Q :
    ``cout_variable_eur`` est le coût proportionnel par pièce
    (2 × surface nette × prix) et ``cout_fixe_eur_par_lot`` le minimum de
    lot. Règle d'agrégation (appliquée en 3.3) :
    **contribution = max(cout_variable_eur, cout_fixe_eur_par_lot ÷ Q)**.
    """

    model_config = ConfigDict(extra="forbid")

    traitement_id: str
    surface_traitee_m2: float
    prix: float
    unite: str
    minimum_lot_eur: float
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocComposants(BaseModel):
    """Bloc 6 — composants achetés & opérations secondaires."""

    model_config = ConfigDict(extra="forbid")

    cout_composants_eur: float
    temps_operations_s: float
    cout_operations_eur: float
    postes_utilises: list[str]
    cout_variable_eur: float
    cout_fixe_eur_par_lot: float


class BlocsCout46(BaseModel):
    """Les blocs 4 à 6 du chiffrage (finition absente si non spécifiée)."""

    model_config = ConfigDict(extra="forbid")

    soudure: BlocSoudure
    finition: BlocFinition | None
    composants: BlocComposants


def calculer_bloc_soudure(piece: PieceExtraite) -> BlocSoudure:
    """Bloc 4 : 0 pour une pièce unique découpée-pliée (V1).

    Raises:
        ErreurChiffrage: la pièce porte des soudures — l'assemblage soudé
            est hors périmètre V1 (jamais un 0 silencieux).
    """
    if piece.soudures:
        msg = (
            f"Assemblage soudé hors périmètre V1 : {len(piece.soudures)} "
            "soudure(s) indiquée(s) sur le plan."
        )
        raise ErreurChiffrage(msg)
    return BlocSoudure()


def calculer_bloc_finition(
    piece: PieceExtraite,
    flan: Flan,
    session: Session,
    traitement_id: str | None = None,
) -> BlocFinition | None:
    """Bloc 5 : coût du traitement de surface.

    Surface traitée = 2 × surface nette du flan (deux faces) ; coût
    proportionnel = surface × prix ; minimum de lot en coût fixe (règle
    d'agrégation ``max(variable, fixe ÷ Q)``, voir ``BlocFinition``).

    Args:
        traitement_id: traitement du référentiel à chiffrer explicitement
            (option proposée hors chiffrage de base, ex. peinture de
            piece_support). Sinon, le type extrait du plan est résolu via
            ``TRAITEMENT_ID_PAR_TYPE``.

    Returns:
        Le bloc, ou None si aucun traitement n'est spécifié sur le plan
        (ou type non chiffrable en V1, ex. « autre »).

    Raises:
        ErreurChiffrage: traitement inconnu du référentiel, ou tarif au kg
            (hors périmètre V1, seuls les tarifs au m² sont chiffrés).
    """
    if traitement_id is None:
        type_t = piece.traitement.type.valeur
        if type_t in (None, "aucun"):
            return None
        traitement_id = TRAITEMENT_ID_PAR_TYPE.get(str(type_t))
        if traitement_id is None:
            return None
    traitement = get_traitement(traitement_id, session)
    if traitement is None:
        msg = f"Traitement inconnu dans le référentiel : {traitement_id!r}."
        raise ErreurChiffrage(msg)
    if traitement.unite != "m2":
        msg = (
            f"Traitement {traitement_id!r} tarifé au {traitement.unite} : "
            "hors périmètre V1 (seuls les tarifs au m² sont chiffrés)."
        )
        raise ErreurChiffrage(msg)
    surface_m2 = 2.0 * flan.surface_nette_mm2 * 1e-6
    return BlocFinition(
        traitement_id=traitement_id,
        surface_traitee_m2=surface_m2,
        prix=traitement.prix,
        unite=traitement.unite,
        minimum_lot_eur=traitement.minimum_lot_eur,
        cout_variable_eur=surface_m2 * traitement.prix,
        cout_fixe_eur_par_lot=traitement.minimum_lot_eur,
    )


def calculer_bloc_composants(
    piece: PieceExtraite,
    composants: list[tuple[str, int]],
    session: Session,
) -> BlocComposants:
    """Bloc 6 : composants achetés + opérations secondaires.

    Règles V1 :

    - coût composants = Σ quantité × prix unitaire (table ``composants``) ;
    - opérations : pose de chaque composant (``operation_id`` du
      référentiel), taraudage par trou fileté (paramètre
      ``operation_taraudage``), ébavurage systématique dès qu'il y a des
      composants ou des taraudages (paramètre ``operation_ebavurage``) —
      une pièce sans composant ni trou fileté a un bloc 6 à zéro ;
    - taux = poste de chaque opération (``operations.poste_id``) ;
    - réglage = ``temps_reglage_min`` de chaque poste **distinct** utilisé.

    Args:
        piece: pièce extraite du plan.
        composants: couples (référence du référentiel ``composants``,
            quantité) retenus pour le chiffrage — la nomenclature extraite
            (``piece.composants``) sert de source à l'appelant.
        session: session SQLAlchemy sur la base de référence.

    Raises:
        ErreurChiffrage: composant, opération ou poste inconnu du
            référentiel.
    """
    zero = BlocComposants(
        cout_composants_eur=0.0,
        temps_operations_s=0.0,
        cout_operations_eur=0.0,
        postes_utilises=[],
        cout_variable_eur=0.0,
        cout_fixe_eur_par_lot=0.0,
    )

    def _poste(poste_id: str | None, contexte: str):
        if poste_id is None:
            msg = f"Pas de poste associé ({contexte})."
            raise ErreurChiffrage(msg)
        poste = get_poste(poste_id, session)
        if poste is None:
            msg = f"Poste inconnu dans le référentiel : {poste_id!r} ({contexte})."
            raise ErreurChiffrage(msg)
        return poste

    # --- Operations applicables : (operation_id, quantité, contexte) -------
    operations: list[tuple[str, int, str]] = []
    cout_composants = 0.0
    for reference, quantite in composants:
        composant = get_composant(reference, session)
        if composant is None:
            msg = f"Composant inconnu dans le référentiel : {reference!r}."
            raise ErreurChiffrage(msg)
        cout_composants += quantite * composant.prix_unitaire_eur
        if composant.operation_id is not None:
            operations.append((composant.operation_id, quantite, f"pose de {reference}"))
    nb_filetes = sum(t.quantite for t in piece.contours.trous if t.filetage)
    if nb_filetes:
        operations.append(
            (str(get_parametre("operation_taraudage", session)), nb_filetes, "taraudage")
        )
    if operations:
        operations.append((str(get_parametre("operation_ebavurage", session)), 1, "ébavurage"))
    if not operations:
        return zero

    # --- Coût des opérations et réglages, par poste ------------------------
    postes: dict[str, float] = {}  # poste_id → taux horaire
    cout_operations = 0.0
    temps_operations = 0.0
    for operation_id, quantite, contexte in operations:
        operation = get_operation(operation_id, session)
        if operation is None:
            msg = f"Opération inconnue dans le référentiel : {operation_id!r} ({contexte})."
            raise ErreurChiffrage(msg)
        poste = _poste(operation.poste_id, f"opération {operation_id}")
        postes[poste.id] = poste.taux_horaire_eur_h
        temps = operation.temps_s * quantite
        temps_operations += temps
        cout_operations += temps / 3600.0 * poste.taux_horaire_eur_h
    reglage = 0.0
    for poste_id in postes:
        poste = _poste(poste_id, "réglage")
        reglage += poste.temps_reglage_min / 60.0 * poste.taux_horaire_eur_h
    return BlocComposants(
        cout_composants_eur=cout_composants,
        temps_operations_s=temps_operations,
        cout_operations_eur=cout_operations,
        postes_utilises=sorted(postes),
        cout_variable_eur=cout_composants + cout_operations,
        cout_fixe_eur_par_lot=reglage,
    )


def calculer_blocs_4_6(
    piece: PieceExtraite,
    flan: Flan,
    session: Session,
    composants: list[tuple[str, int]] | None = None,
) -> BlocsCout46:
    """Calcule les blocs 4 à 6 du chiffrage (soudure, finition, composants).

    La finition n'est calculée que si un traitement est spécifié sur le
    plan ; pour chiffrer une option (ex. peinture proposée), appeler
    ``calculer_bloc_finition`` explicitement avec un ``traitement_id``.
    """
    return BlocsCout46(
        soudure=calculer_bloc_soudure(piece),
        finition=calculer_bloc_finition(piece, flan, session),
        composants=calculer_bloc_composants(piece, composants or [], session),
    )


# ---------------------------------------------------------------------------
# Agrégation (issue #15) : coût de revient, prix, paliers de quantité, trace
# ---------------------------------------------------------------------------


class LigneTrace(BaseModel):
    """Trace d'une ligne de calcul (formule, valeurs, origine des données).

    Figeable : sérialisée telle quelle dans le résultat, elle ne change
    plus si un prix de référence évolue ensuite (architecture §Étape 5).
    ``date_prix`` n'est renseigné que pour les tables qui portent une date
    de mise à jour (``matieres.date_maj``) — None ailleurs.
    """

    model_config = ConfigDict(extra="forbid")

    bloc: str
    formule: str
    valeurs: dict[str, float | int | str | None]
    table_origine: str
    date_prix: date | None = None


class PalierPrix(BaseModel):
    """Coût et prix unitaires à un palier de quantité."""

    model_config = ConfigDict(extra="forbid")

    quantite: int
    cout_unitaire_eur: float
    prix_unitaire_eur: float


class Chiffrage(BaseModel):
    """Résultat complet du chiffrage : blocs, paliers, trace."""

    model_config = ConfigDict(extra="forbid")

    blocs_1_3: BlocsCout
    blocs_4_6: BlocsCout46
    paliers: list[PalierPrix]
    trace: list[LigneTrace]


def chiffrer(
    piece: PieceExtraite,
    matiere_id: str,
    session: Session,
    quantites: list[int] | None = None,
    composants: list[tuple[str, int]] | None = None,
    client_id: str | None = None,
) -> Chiffrage:
    """Chiffre une pièce : agrégation des 6 blocs, marge, paliers, trace.

    - coût de revient(Q) = Σ variables unitaires + Σ réglages ÷ Q
      (+ contribution finition ``max(variable, fixe ÷ Q)`` si traitement) ;
    - prix unitaire HT = coût ÷ (1 − marge) ; marge spécifique du client si
      fournie, sinon paramètre ``marge_defaut`` (§4) ;
    - paliers : argument ``quantites`` ou paramètre ``paliers_quantite`` (§5) ;
    - chaque ligne de calcul est tracée (formule, valeurs, table d'origine).

    Raises:
        ErreurChiffrage: faisabilité bloquante, quantité ≤ 0, matière ou
            client inconnu du référentiel.
    """
    if quantites is None:
        quantites = cast(list[int], get_parametre("paliers_quantite", session))
    if not quantites or any(q <= 0 for q in quantites):
        msg = f"Paliers de quantité invalides : {quantites}."
        raise ErreurChiffrage(msg)

    matiere = get_matiere(matiere_id, session)
    if matiere is None:
        msg = f"Matière inconnue dans le référentiel : {matiere_id!r}."
        raise ErreurChiffrage(msg)
    constats = evaluer_faisabilite(piece, matiere_id, session)
    blocages = [c for c in constats if c.severite == "blocage"]
    if blocages:
        details = " ; ".join(c.message for c in blocages)
        msg = f"Pièce non chiffrable (faisabilité bloquante) : {details}"
        raise ErreurChiffrage(msg)
    facteur_k = float(get_parametre("facteur_k", session))
    flan = construire_flan(piece, matiere.densite_kg_dm3, facteur_k)

    blocs_1_3 = calculer_blocs_1_3(piece, flan, matiere_id, session)
    blocs_4_6 = calculer_blocs_4_6(piece, flan, session, composants)

    marge = float(get_parametre("marge_defaut", session))
    if client_id is not None:
        client = get_client(client_id, session)
        if client is None:
            msg = f"Client inconnu dans le référentiel : {client_id!r}."
            raise ErreurChiffrage(msg)
        if client.marge_specifique is not None:
            marge = client.marge_specifique

    variable = (
        blocs_1_3.matiere.cout_variable_eur
        + blocs_1_3.decoupe.cout_variable_eur
        + blocs_1_3.pliage.cout_variable_eur
        + blocs_4_6.soudure.cout_variable_eur
        + blocs_4_6.composants.cout_variable_eur
    )
    fixe = (
        blocs_1_3.matiere.cout_fixe_eur_par_lot
        + blocs_1_3.decoupe.cout_fixe_eur_par_lot
        + blocs_1_3.pliage.cout_fixe_eur_par_lot
        + blocs_4_6.soudure.cout_fixe_eur_par_lot
        + blocs_4_6.composants.cout_fixe_eur_par_lot
    )
    finition = blocs_4_6.finition

    paliers: list[PalierPrix] = []
    for q in quantites:
        cout = variable + fixe / q
        if finition is not None:
            cout += max(finition.cout_variable_eur, finition.cout_fixe_eur_par_lot / q)
        paliers.append(
            PalierPrix(
                quantite=q,
                cout_unitaire_eur=cout,
                prix_unitaire_eur=cout / (1.0 - marge),
            )
        )

    trace = [
        LigneTrace(
            bloc="matiere",
            formule="masse flan ÷ rendement calepinage × prix matière",
            valeurs={
                "masse_flan_kg": blocs_1_3.matiere.masse_flan_kg,
                "rendement": blocs_1_3.matiere.rendement_calepinage,
                "prix_eur_kg": blocs_1_3.matiere.prix_matiere_eur_kg,
                "cout_variable_eur": blocs_1_3.matiere.cout_variable_eur,
            },
            table_origine="matieres",
            date_prix=matiere.date_maj,
        ),
        LigneTrace(
            bloc="decoupe",
            formule="(longueur de coupe ÷ vitesse + amorçages × temps par amorçage) × taux ; réglage × taux",
            valeurs={
                "longueur_coupe_mm": blocs_1_3.decoupe.longueur_coupe_mm,
                "nombre_amorcages": blocs_1_3.decoupe.nombre_amorcages,
                "vitesse_m_min": blocs_1_3.decoupe.vitesse_m_min,
                "temps_cycle_s": blocs_1_3.decoupe.temps_cycle_s,
                "taux_horaire_eur_h": blocs_1_3.decoupe.taux_horaire_eur_h,
                "cout_variable_eur": blocs_1_3.decoupe.cout_variable_eur,
                "cout_fixe_eur_par_lot": blocs_1_3.decoupe.cout_fixe_eur_par_lot,
            },
            table_origine="vitesses_coupe, postes",
        ),
        LigneTrace(
            bloc="pliage",
            formule="nb plis × temps par pli × taux ; réglage × taux",
            valeurs={
                "nb_plis": blocs_1_3.pliage.nb_plis,
                "temps_par_pli_s": blocs_1_3.pliage.temps_par_pli_s,
                "taux_horaire_eur_h": blocs_1_3.pliage.taux_horaire_eur_h,
                "cout_variable_eur": blocs_1_3.pliage.cout_variable_eur,
                "cout_fixe_eur_par_lot": blocs_1_3.pliage.cout_fixe_eur_par_lot,
            },
            table_origine="temps_pliage, postes",
        ),
        LigneTrace(
            bloc="soudure",
            formule="0 (pièce unique, V1)",
            valeurs={"cout_variable_eur": 0.0, "cout_fixe_eur_par_lot": 0.0},
            table_origine="—",
        ),
        LigneTrace(
            bloc="composants",
            formule="Σ qté × prix + Σ temps opération × taux poste ; réglages par poste",
            valeurs={
                "cout_composants_eur": blocs_4_6.composants.cout_composants_eur,
                "temps_operations_s": blocs_4_6.composants.temps_operations_s,
                "cout_operations_eur": blocs_4_6.composants.cout_operations_eur,
                "cout_variable_eur": blocs_4_6.composants.cout_variable_eur,
                "cout_fixe_eur_par_lot": blocs_4_6.composants.cout_fixe_eur_par_lot,
            },
            table_origine="composants, operations, postes",
        ),
        LigneTrace(
            bloc="marge",
            formule="prix = coût ÷ (1 − marge)",
            valeurs={"marge": marge, "client_id": client_id},
            table_origine="parametres",
        ),
    ]
    if finition is not None:
        trace.append(
            LigneTrace(
                bloc="finition",
                formule="max(2 × surface nette × prix, minimum de lot ÷ Q)",
                valeurs={
                    "traitement_id": finition.traitement_id,
                    "surface_traitee_m2": finition.surface_traitee_m2,
                    "prix": finition.prix,
                    "minimum_lot_eur": finition.minimum_lot_eur,
                },
                table_origine="traitements",
            )
        )

    return Chiffrage(blocs_1_3=blocs_1_3, blocs_4_6=blocs_4_6, paliers=paliers, trace=trace)
