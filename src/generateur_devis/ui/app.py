"""Interface Streamlit du parcours devis (étapes 1 et 4, issues #23 et #24).

Lancement : ``uv run streamlit run src/generateur_devis/ui/app.py``.

Écran unique conditionné par ``st.session_state`` (YAGNI V1) : dépôt du plan
tant qu'il n'y a pas de résultat, validation humaine ensuite. Couche de
présentation **fine** : tout le calcul est dans ``ui.pipeline`` ; le rendu 3D
est dans ``ui.rendu3d``.
"""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import Collection, MutableMapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import pandas as pd
import streamlit as st

from generateur_devis.calcul_prix import calculer_bloc_finition
from generateur_devis.controles_prix import evaluer_controles_prix
from generateur_devis.data.acces import (
    TRAITEMENT_ID_PAR_TYPE,
    get_client,
    get_parametre,
    get_traitement,
    list_clients,
    list_matieres,
)
from generateur_devis.data.db import get_session
from generateur_devis.devis import Devis, Modification, emettre
from generateur_devis.extraction.correction import (
    ErreurCorrection,
    PropositionCorrection,
    proposer_correction,
)
from generateur_devis.modele3d import ErreurGeometrie, construire_modele_3d
from generateur_devis.pdf import generer_pdf_client
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui.formatage import formater_valeur
from generateur_devis.ui.pipeline import ResultatDevis, orchestrer_devis, rechiffrer
from generateur_devis.ui.rendu3d import maillage_vers_figure
from generateur_devis.ui.ventilation import lignes_trace, ventilation_couts
from generateur_devis.unites import ConversionUnites, message_unites, valeur_origine

TYPES_PLAN = ["pdf", "png", "jpg", "jpeg", "webp"]
CLE_RESULTAT = "resultat_devis"
CLE_DEVIS = "devis"
CLE_CONTEXTE = "contexte"
CLE_PIECE_CORRIGEE = "piece_corrigee"
CLE_PROPOSITION = "proposition_correction"
CLE_CORRECTIONS = "corrections_ia"

# Garde-fous d'UI des champs bornés : une seule source pour ``min_value=`` et
# pour la détection des valeurs initiales hors bornes (issue #58).
EPAISSEUR_MIN_MM = 0.1
LARGEUR_MIN_MM = 1.0
RAYON_MIN_MM = 0.1

# Clés purgées au retour au dépôt : état de la validation en cours + widgets à
# clé (sinon les éditions du data_editor du plan précédent sont rejouées sur le
# plan suivant). CLE_CONTEXTE (client, quantités) est conservé.
CLES_VALIDATION = (
    CLE_RESULTAT,
    CLE_PIECE_CORRIGEE,
    CLE_PROPOSITION,
    CLE_CORRECTIONS,
    "texte_en_cours",
    "texte_correction",
    "editeur_profil",
    "editeur_trous",
)


@dataclass(frozen=True)
class ValeurInitiale:
    """Pré-saisie d'un champ borné et son origine, affichée sous le champ."""

    valeur: float | None  # injectée dans st.number_input(value=...) — None = vide
    origine: Literal["plan", "defaut", "absente", "hors_bornes"]
    explication: str  # toujours non vide


def _nombre_fr(valeur: float) -> str:
    """0.06 → « 0,06 » (format ``:g``, virgule décimale)."""
    return f"{valeur:g}".replace(".", ",")


def _mm_fr(valeur: float) -> str:
    """1.524 → « 1,52 » (précision d'affichage des mm, stockage exact)."""
    return formater_valeur("valeur_mm", valeur).replace(".", ",")


def valeur_initiale(
    libelle: str,
    lue: float | None,
    minimum: float,
    defaut: tuple[float, str] | None = None,
    unite: str = "mm",
    lue_sur_plan: str | None = None,
) -> ValeurInitiale:
    """Valeur à pré-saisir dans un champ borné, avec l'origine de la valeur.

    - lue >= minimum → origine ``plan`` ;
    - absente (None) avec ``defaut`` = (valeur, origine lisible) >= minimum →
      origine ``defaut``, « à confirmer » ;
    - absente sans défaut → champ vide, origine ``absente`` (bloquant) ;
    - lue (ou défaut) < minimum, <= 0 ou NaN → champ vide, origine
      ``hors_bornes`` (bloquant). Jamais remplacée par le minimum en silence,
      et une lecture aberrante ne retombe pas sur le défaut.

    ``lue_sur_plan`` : lecture d'origine quand ``lue`` vient d'une conversion
    (ex. « 0,06 in », issue #57) — affichée « 0,06 in → 1,52 mm ».
    """
    minimum_txt = f"minimum {_nombre_fr(minimum)} {unite}"
    if lue is None and defaut is None:
        return ValeurInitiale(None, "absente", f"{libelle} : non lu sur le plan, à saisir.")
    if lue is None:
        valeur, source = defaut
        desc = f"défaut atelier {_nombre_fr(valeur)} {unite} ({source})"
        if not valeur >= minimum:  # NaN compris
            return ValeurInitiale(
                None,
                "hors_bornes",
                f"{libelle} : absent du plan, {desc} hors bornes ({minimum_txt}), à saisir.",
            )
        return ValeurInitiale(valeur, "defaut", f"{libelle} : absent du plan, {desc}, à confirmer.")
    if not lue >= minimum:  # NaN compris
        lu_txt = (
            f"{lue_sur_plan} → {_mm_fr(lue)} {unite}"
            if lue_sur_plan
            else f"{_nombre_fr(lue)} {unite}"
        )
        return ValeurInitiale(
            None,
            "hors_bornes",
            f"{libelle} : valeur lue hors bornes : {lu_txt} ({minimum_txt}), à saisir.",
        )
    if lue_sur_plan:
        return ValeurInitiale(
            lue, "plan", f"{libelle} : lu sur le plan : {lue_sur_plan} → {_mm_fr(lue)} {unite}."
        )
    return ValeurInitiale(lue, "plan", f"{libelle} : lu sur le plan.")


@dataclass(frozen=True)
class MatiereInitiale:
    """Pré-sélection de la liste « Matière » et son origine (issue #55)."""

    matiere_id: str | None  # id du référentiel à pré-sélectionner ; None = liste vide
    origine: Literal["depot", "plan", "assistant", "inconnue", "absente"]
    explication: str  # toujours non vide, affichée sous la liste (⛔ si matiere_id is None)
    alerte: str | None = None  # conflit dépôt ≠ plan → ⚠️ en tête du formulaire


def matiere_initiale(
    matiere_depot: str | None,
    designation: str | None,
    ids_connus: Collection[str],
    corrigee: bool = False,
) -> MatiereInitiale:
    """Matière à pré-sélectionner : choix du dépôt, sinon désignation de la pièce si
    elle est un id du référentiel, sinon aucune. Jamais de repli sur une matière
    arbitraire. Même priorité que ``pipeline._resoudre_matiere``.

    ``designation`` : ``piece.matiere.designation.valeur`` de la pièce affichée
    (espaces retirés ; "" traité comme None). Correspondance exacte (sensible à
    la casse), comme ``get_matiere``. ``corrigee`` : True si cette désignation a
    été modifiée par l'assistant (diff accepté), pour annoncer la bonne origine.
    ``ids_connus`` : identifiants des matières du référentiel (la base).
    """
    designation = (designation or "").strip() or None
    source = "la correction de l'assistant" if corrigee else "le plan"
    prefixe = ""
    if matiere_depot is not None and matiere_depot not in ids_connus:
        prefixe = f"Choix du dépôt « {matiere_depot} » inconnu du référentiel ; "
        matiere_depot = None

    if matiere_depot is not None:
        if designation is None:
            return MatiereInitiale(
                matiere_depot, "depot", "Matière : choisie au dépôt (absente du plan)."
            )
        if designation == matiere_depot:
            return MatiereInitiale(
                matiere_depot, "depot", "Matière : choisie au dépôt, identique au plan."
            )
        return MatiereInitiale(
            matiere_depot,
            "depot",
            "Matière : choisie au dépôt.",
            f"⚠️ Matière : choix du dépôt {matiere_depot} retenu, "
            f"{source} indique « {designation} ».",
        )
    if designation is None:
        return MatiereInitiale(
            None,
            "absente",
            prefixe + "Matière : absente du plan et non choisie au dépôt : à choisir.",
        )
    if designation in ids_connus:
        if corrigee:
            return MatiereInitiale(
                designation, "assistant", prefixe + "Matière : corrigée par l'assistant."
            )
        return MatiereInitiale(designation, "plan", prefixe + "Matière : lue sur le plan.")
    lue = "corrigée par l'assistant" if corrigee else "lue sur le plan"
    return MatiereInitiale(
        None,
        "inconnue",
        prefixe + f"Matière : « {designation} » {lue}, inconnue du référentiel : à choisir.",
    )


def revenir_au_depot(etat: MutableMapping[str, object]) -> None:
    """Retire de ``etat`` (le session_state) les clés de CLES_VALIDATION."""
    for cle in CLES_VALIDATION:
        etat.pop(cle, None)


def _journaliser_correction(texte: str, proposition: PropositionCorrection, issue: str) -> None:
    """Accumule la correction proposée et son issue (injectée au Devis à la validation)."""
    st.session_state.setdefault(CLE_CORRECTIONS, []).append(
        {
            "texte": texte,
            "nb_modifications": len(proposition.diffs),
            "issue": issue,  # acceptee | refusee
        }
    )


def _ecran_assistant(piece: PieceExtraite) -> None:
    """Assistant de correction en texte libre (issue #25, architecture §9).

    L'IA propose un diff borné, affiché avant/après ; l'utilisateur accepte
    ou refuse explicitement — aucun changement sans accord.
    """
    contexte = st.session_state.get(CLE_CONTEXTE, {})
    nom_modele = contexte.get("nom_modele")

    with st.expander("✏️ Corriger en texte libre (assistant IA)"):
        proposition: PropositionCorrection | None = st.session_state.get(CLE_PROPOSITION)

        if proposition is None:
            texte = st.text_area(
                "Décrivez la correction",
                placeholder="Ex. « c'est de l'inox 2 mm avec 4 écrous M6 »",
                key="texte_correction",
            )
            if st.button("Proposer une correction", disabled=not nom_modele or not texte.strip()):
                try:
                    with st.spinner("L'assistant analyse la correction…"):
                        proposition = proposer_correction(piece, texte, nom_modele)
                    st.session_state[CLE_PROPOSITION] = proposition
                    st.session_state["texte_en_cours"] = texte
                    st.rerun()
                except ErreurCorrection as e:
                    st.error(str(e))
            return

        # --- Affichage avant / après ------------------------------------------
        st.caption(f"Correction : « {st.session_state.get('texte_en_cours', '')} »")
        if proposition.remarque:
            st.info(f"💬 {proposition.remarque}")
        st.table(
            {
                "Champ": [c for c, _, _, _ in proposition.ligne_avant_apres(piece)],
                "Avant": [a for _, a, _, _ in proposition.ligne_avant_apres(piece)],
                "Après": [b for _, _, b, _ in proposition.ligne_avant_apres(piece)],
                "Justification": [j for _, _, _, j in proposition.ligne_avant_apres(piece)],
            }
        )
        try:
            piece_apres = proposition.appliquer(piece)
            for probleme in piece_apres.problemes_coherence():
                st.warning(f"⚠️ Après application : {probleme}")
        except ErreurCorrection as e:
            st.error(f"Correction inapplicable : {e}")
            piece_apres = None

        col_ok, col_non = st.columns(2)
        with col_ok:
            if st.button("✅ Accepter", disabled=piece_apres is None):
                st.session_state[CLE_PIECE_CORRIGEE] = piece_apres
                _journaliser_correction(
                    st.session_state.get("texte_en_cours", ""), proposition, "acceptee"
                )
                st.session_state.pop(CLE_PROPOSITION, None)
                st.rerun()
        with col_non:
            if st.button("❌ Refuser"):
                _journaliser_correction(
                    st.session_state.get("texte_en_cours", ""), proposition, "refusee"
                )
                st.session_state.pop(CLE_PROPOSITION, None)
                st.rerun()


def _champs_peu_surs(piece: PieceExtraite, session) -> list[str]:
    """Champs du parcours lus avec une confiance sous le seuil (anomalies en tête).

    Seuil lu dans le paramètre ``seuil_confiance_champs`` (aucune valeur en dur).
    """
    seuil = float(get_parametre("seuil_confiance_champs", session))
    champs: list[tuple[str, Champ]] = [
        ("unité du plan", piece.unites),
        ("matière (désignation)", piece.matiere.designation),
        ("épaisseur", piece.matiere.epaisseur),
        ("largeur d'encombrement", piece.encombrement.largeur),
        ("référence", piece.identification.reference),
        ("désignation pièce", piece.identification.designation),
    ]
    return [
        f"{nom} : confiance {champ.confiance:.0%}"
        for nom, champ in champs
        if champ.confiance is not None and champ.confiance < seuil
    ]


def _ecran_restitution() -> None:
    """Écran 3 : restitution — vue interne / vue client, marge, émission (4.5).

    Vue interne : tracé complet + encart « Le modèle propose ». Vue client :
    prix et quantités seulement — les coûts ne sortent jamais (§6). Le PDF
    client est généré à l'émission.
    """
    st.title("Restitution")
    devis: Devis = st.session_state[CLE_DEVIS]
    lecture_seule = devis.statut == "emis"
    if lecture_seule:
        st.info(f"Devis {devis.id} émis le {devis.date_emission:%d/%m/%Y} — lecture seule.")

    # --- Encart « Le modèle propose » (vue interne) ----------------------------
    piece = devis.piece_validee
    with st.expander("🤖 Le modèle propose", expanded=False):
        with get_session() as session_encart:
            champs = _champs_peu_surs(piece, session_encart)
        if champs:
            st.caption("Champs lus avec confiance faible (corrigés ou à surveiller) :")
            for champ in champs:
                st.write(f"- {champ}")
        corrections = [m for m in devis.modifications if m.champ == "correction_ia"]
        if corrections:
            st.caption("Corrections de l'assistant (proposées et leur issue) :")
            for correction in corrections:
                st.write(f"- « {correction.avant} » → {correction.apres}")
        if not champs and not corrections:
            st.write("Extraction conforme, aucune correction.")

    # --- Vue client : prix et quantités seulement (§6) --------------------------
    st.subheader("Vue client")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "quantite": p.quantite,
                    "prix_unitaire_eur": float(
                        formater_valeur("prix_unitaire_eur", p.prix_unitaire_eur)
                    ),
                    "prix_total_eur": float(
                        formater_valeur(
                            "prix_unitaire_eur", p.prix_unitaire_eur * p.quantite
                        )
                    ),
                }
                for p in devis.chiffrage.paliers
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    # --- Marge (modifiable jusqu'à l'émission, rechiffrée depuis coûts figés) ---
    if not lecture_seule:
        with st.form("marge"):
            marge = st.number_input(
                "Marge",
                min_value=0.0,
                max_value=0.95,
                value=float(devis.marge),
                step=0.01,
                format="%.2f",
            )
            if st.form_submit_button("Appliquer la marge") and marge != devis.marge:
                devis.changer_marge(devis.auteur or "inconnu", marge)
                st.rerun()

    # --- Vue interne : alertes (contrôles prix, comparaison historique) ----------
    # Recalculées depuis le Devis (pièce, flan, matière validés, marge courante),
    # jamais lues sur le résultat du dépôt (issue #54).
    with get_session() as session_alertes:
        alertes = evaluer_controles_prix(
            devis.chiffrage, devis.piece_validee, devis.flan, devis.matiere_id, session_alertes
        )
    for alerte in alertes:
        st.warning(f"⚖️ Contrôle prix ({alerte.regle}) : {alerte.message}")

    # --- Vue interne : tracé complet ---------------------------------------------
    with st.expander("🔍 Vue interne — tracé du calcul"):
        st.write(
            f"Coût palier commandé ({devis.quantite_commandee}) : "
            f"**{formater_valeur('cout_unitaire_eur', devis.palier_commande().cout_unitaire_eur)} €** "
            f"— marge {devis.marge:.0%}"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"bloc": t.bloc, "formule": t.formule, "table": t.table_origine}
                    for t in devis.chiffrage.trace
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    # --- Émission : historique + PDF client ---------------------------------------
    if not lecture_seule:
        if st.button("📤 Émettre le devis", type="primary"):
            with get_session() as session:
                emettre(devis, devis.auteur or "inconnu", session)
                session.commit()
            st.session_state["pdf_client"] = generer_pdf_client(
                devis,
                int(get_parametre("validite_devis_jours", session)),
                str(get_parametre("conditions_generales", session)),
            )
            st.rerun()
    if "pdf_client" in st.session_state:
        st.download_button(
            "📄 Télécharger le PDF client",
            data=st.session_state["pdf_client"],
            file_name=f"{devis.id}.pdf",
            mime="application/pdf",
        )

    if st.button("Nouveau devis"):
        for cle in (
            CLE_RESULTAT,
            CLE_DEVIS,
            CLE_CONTEXTE,
            CLE_PIECE_CORRIGEE,
            CLE_PROPOSITION,
            CLE_CORRECTIONS,
            "pdf_client",
        ):
            st.session_state.pop(cle, None)
        st.rerun()


def main() -> None:
    if st.session_state.get(CLE_DEVIS) is not None:
        _ecran_restitution()
        return
    if st.session_state.get(CLE_RESULTAT) is None:
        ecran_depot()
    else:
        ecran_validation()


# ---------------------------------------------------------------------------
# Écran 1 — dépôt du plan et contexte commercial (issue #23)
# ---------------------------------------------------------------------------


def ecran_depot() -> ResultatDevis | None:
    """Écran 1 : dépôt du plan + contexte commercial + lancement du pipeline."""
    st.title("Nouveau devis — dépôt du plan")

    plan = st.file_uploader("Plan (PDF ou image)", type=TYPES_PLAN)
    with get_session() as session:
        choix_clients = {c.nom: c.id for c in list_clients(session)}
        choix_matieres = _choix_matieres(session)
        paliers = [str(q) for q in get_parametre("paliers_quantite", session)]

    col1, col2 = st.columns(2)
    with col1:
        nom_client = st.selectbox("Client", ["(sans)"] + list(choix_clients))
        client_id = choix_clients.get(nom_client)
        matiere = st.selectbox(
            "Matière (prioritaire sur le plan)", ["(à extraire)"] + list(choix_matieres)
        )
        matiere_id = None if matiere == "(à extraire)" else choix_matieres[matiere]
    with col2:
        saisie = st.text_input("Quantités (séparées par des virgules)", ", ".join(paliers))
        quantites: list[int] | None = None
        try:
            quantites = [int(q.strip()) for q in saisie.split(",") if q.strip()]
            if not quantites or any(q <= 0 for q in quantites):
                raise ValueError
        except ValueError:
            st.error("Quantités invalides : entiers positifs séparés par des virgules.")
    # Modèle d'extraction : paramètre administrable (agent 5.2), invisible ici ;
    # la variable d'environnement MODELE_EXTRACTION surcharge le paramètre.
    with get_session() as session:
        nom_modele = os.environ.get("MODELE_EXTRACTION") or get_parametre(
            "modele_extraction", session
        )

    if st.button(
        "Lancer l'analyse",
        disabled=plan is None or not nom_modele or quantites is None,
    ):
        with st.spinner("Extraction et chiffrage en cours…"), get_session() as session:
            resultat = orchestrer_devis(
                plan.read(),
                plan.name,
                client_id,
                quantites,
                matiere_id,
                nom_modele,
                session,
            )
        if resultat.piece is None:
            # Aucune pièce (fichier illisible, extraction impossible) : on reste
            # sur le dépôt, formulaire complet, pour déposer un autre fichier.
            st.error(resultat.erreur or "Aucune pièce extraite.")
        else:
            st.session_state[CLE_RESULTAT] = resultat
            st.session_state[CLE_CONTEXTE] = {
                "client_id": client_id,
                "quantites": quantites,
                "nom_modele": nom_modele,
                "matiere_id": matiere_id,  # choix du dépôt, None si « (à extraire) »
            }
            st.rerun()

    return st.session_state.get(CLE_RESULTAT)


def _afficher_constats(resultat: ResultatDevis) -> None:
    """Blocages et alertes : faisabilité d'abord, contrôles de prix ensuite."""
    for constat in resultat.constats:
        if constat.severite == "blocage":
            st.error(f"⛔ {constat.regle} — {constat.message}")
        else:
            st.warning(f"⚠️ {constat.regle} — {constat.message}")
    for constat in resultat.alertes_controles:
        st.warning(f"⚠️ {constat.regle} — {constat.message}")


# ---------------------------------------------------------------------------
# Écran 2 — validation humaine (issue #24)
# ---------------------------------------------------------------------------


def _nombre(valeur: object) -> float | None:
    """Nombre lu d'une cellule de data_editor, ou None si vide/NaN.

    ``st.data_editor`` renvoie ``NaN`` pour une cellule numérique vidée, et
    ``NaN`` est truthy — il doit être traité comme une valeur absente.
    """
    if valeur is None or valeur == "":
        return None
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(nombre) else nombre


def _valider_lignes(lignes_profil: list[dict], lignes_trous: list[dict]) -> list[str]:
    """Valide les lignes des data_editor — aucune suppression silencieuse.

    Schéma attendu (documenté pour la conversion DataFrame → schéma pièce) :
    - profil : ``type`` (« aile » | « pli »), ``longueur`` (aile, mm > 0),
      ``angle`` (pli, degrés), ``sens`` (pli, « haut » | « bas ») ;
    - trous : ``forme``, ``diametre`` (mm > 0), ``quantite`` (≥ 1).

    Une ligne entièrement vide est ignorée (ligne neuve du data_editor) ;
    une ligne **partiellement** remplie est une erreur explicite — elle ne
    doit jamais disparaître du chiffrage sans avertissement.
    """
    erreurs: list[str] = []
    for i, ligne in enumerate(lignes_profil, start=1):
        remplie = any(v is not None and v != "" for v in ligne.values())
        if not remplie:
            continue
        type_, longueur, angle, sens = (
            ligne.get("type"),
            _nombre(ligne.get("longueur")),
            _nombre(ligne.get("angle")),
            ligne.get("sens"),
        )
        if type_ == "aile":
            if longueur is None or longueur <= 0:
                erreurs.append(f"Profil ligne {i} : aile sans longueur valide.")
        elif type_ == "pli":
            if angle is None:
                erreurs.append(f"Profil ligne {i} : pli sans angle.")
            if sens not in ("haut", "bas"):
                erreurs.append(f"Profil ligne {i} : sens du pli « haut » ou « bas » attendu.")
        else:
            erreurs.append(f"Profil ligne {i} : type « aile » ou « pli » attendu, reçu {type_!r}.")
    for i, ligne in enumerate(lignes_trous, start=1):
        remplie = any(
            (v is not None and v != "") and not (isinstance(v, float) and math.isnan(v))
            for v in ligne.values()
        )
        if not remplie:
            continue
        forme = ligne.get("forme") or "rond"
        diametre, quantite = _nombre(ligne.get("diametre")), _nombre(ligne.get("quantite"))
        longueur, largeur = _nombre(ligne.get("longueur")), _nombre(ligne.get("largeur"))
        if forme == "rond":
            if diametre is None or diametre <= 0:
                erreurs.append(f"Trou ligne {i} : diamètre manquant ou invalide.")
        elif forme in ("oblong", "carre", "rectangulaire"):
            if longueur is None or longueur <= 0 or largeur is None or largeur <= 0:
                erreurs.append(
                    f"Trou ligne {i} : longueur et largeur requises pour un trou {forme}."
                )
            elif forme == "oblong" and longueur <= largeur:
                erreurs.append(
                    f"Trou ligne {i} : un trou oblong attend longueur > largeur."
                )
        else:  # « autre » : aire indéterminable, le calcul le refuserait plus loin
            erreurs.append(
                f"Trou ligne {i} : forme « autre » non chiffrable — préciser la forme."
            )
        if quantite is None or quantite < 1:
            erreurs.append(f"Trou ligne {i} : quantité ≥ 1 attendue.")
    return erreurs


def _choix_matieres(session) -> dict[str, str]:
    """Libellés lisibles → identifiants : « S235JR — acier (EN 10025) »."""
    return {
        f"{m.id} — {m.famille} ({m.norme})": m.id for m in list_matieres(session)
    }


def _lue(valeur: float | None) -> float | None:
    """Valeur lue sur le plan, NaN conservé (signalé hors bornes, pas absent)."""
    return None if valeur is None else float(valeur)


def _champ_borne(
    libelle: str, initiale: ValeurInitiale, minimum: float, step: float, **options
) -> float | None:
    """``st.number_input`` borné + origine de sa valeur affichée dessous."""
    saisie = st.number_input(
        libelle, min_value=minimum, value=initiale.valeur, step=step, **options
    )
    bloquant = saisie is None and initiale.origine in ("absente", "hors_bornes")
    st.caption(("⛔ " if bloquant else "") + initiale.explication)
    return saisie


def _en_pouces(
    conversion: ConversionUnites | None, chemin: str, valeur: float | None
) -> str | None:
    """« 0,06 in » si la valeur actuelle est celle issue de la conversion (#57)."""
    origine = valeur_origine(conversion, chemin, valeur)
    return None if origine is None else f"{_nombre_fr(origine)} in"


def _afficher_unites(conversion: ConversionUnites) -> None:
    """Unité d'origine du plan, et valeurs converties en mm par le code (#57)."""
    niveau, message = message_unites(conversion)
    if niveau == "alerte":
        st.warning(f"⚠️ {message}")
        return
    st.info(message)
    if conversion.valeurs:
        with st.expander("Valeurs converties"):
            st.markdown(
                "\n".join(
                    f"- {v.chemin} : {_nombre_fr(v.valeur_origine)} in → {_mm_fr(v.valeur_mm)} mm"
                    for v in conversion.valeurs
                )
            )


def _editer_piece(
    piece: PieceExtraite,
    choix_matieres: dict[str, str],
    matiere: MatiereInitiale,
    conversion: ConversionUnites | None = None,
) -> tuple[PieceExtraite | None, str | None, list[str]]:
    """Formulaire borné V1 : matière, épaisseur, largeur, profil de pliage, trous.

    Retourne la pièce reconstruite, la matière choisie et les erreurs de
    saisie. Les valeurs par défaut à confirmer s'affichent en ⚠️ en tête du
    formulaire, l'origine de chaque valeur sous son champ. En cas
    d'erreur, la pièce est None : pas de recalcul sur un formulaire
    incomplet (jamais de suppression silencieuse d'un élément), mais tout le
    formulaire est rendu. Streamlit ré-exécute le script à chaque
    modification : le recalcul est donc immédiat (§4).
    """
    # Épaisseur et largeur : pas de défaut (une valeur arbitraire serait une
    # valeur en dur) — absente ou hors bornes → champ vide + ⛔ (issue #58).
    # Plan en pouces : la lecture d'origine est rappelée sous le champ (#57).
    epaisseur_lue = _lue(piece.matiere.epaisseur.valeur)
    largeur_lue = _lue(piece.encombrement.largeur.valeur)
    initiales = {
        "Épaisseur (mm)": valeur_initiale(
            "Épaisseur (mm)",
            epaisseur_lue,
            EPAISSEUR_MIN_MM,
            lue_sur_plan=_en_pouces(conversion, "matiere.epaisseur.valeur", epaisseur_lue),
        ),
        "Largeur d'encombrement (mm)": valeur_initiale(
            "Largeur d'encombrement (mm)",
            largeur_lue,
            LARGEUR_MIN_MM,
            lue_sur_plan=_en_pouces(conversion, "encombrement.largeur.valeur", largeur_lue),
        ),
    }
    # Rayon général : cote du plan si extraite, sinon défaut atelier
    # administrable (paramètre rayon_pliage_defaut_mm), à confirmer.
    rayon_extrait = piece.profil_pliage.rayon_pliage_general if piece.profil_pliage else None
    defaut_rayon = None
    if rayon_extrait is None:
        with get_session() as session:
            defaut_rayon = (
                float(get_parametre("rayon_pliage_defaut_mm", session)),
                "paramètre rayon_pliage_defaut_mm",
            )
    initiales["Rayon de pliage général (mm)"] = valeur_initiale(
        "Rayon de pliage général (mm)",
        _lue(rayon_extrait),
        RAYON_MIN_MM,
        defaut_rayon,
        lue_sur_plan=_en_pouces(conversion, "profil_pliage.rayon_pliage_general", rayon_extrait),
    )
    if matiere.alerte:
        st.warning(matiere.alerte)
    for initiale in initiales.values():
        if initiale.origine == "defaut":
            st.warning(f"⚠️ {initiale.explication}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        # Pré-sélection sans repli sur l'index 0 : aucune matière connue →
        # liste vide + ⛔, choix explicite exigé (issue #55).
        ids = list(choix_matieres.values())
        index = ids.index(matiere.matiere_id) if matiere.matiere_id else None
        libelle = st.selectbox(
            "Matière", list(choix_matieres), index=index, placeholder="Choisir une matière"
        )
        matiere_id = choix_matieres[libelle] if libelle is not None else None
        st.caption(("⛔ " if matiere_id is None else "") + matiere.explication)
    with col2:
        epaisseur = _champ_borne(
            "Épaisseur (mm)", initiales["Épaisseur (mm)"], EPAISSEUR_MIN_MM, 0.5
        )
    with col3:
        largeur = _champ_borne(
            "Largeur d'encombrement (mm)",
            initiales["Largeur d'encombrement (mm)"],
            LARGEUR_MIN_MM,
            5.0,
        )
    with col4:
        rayon_general = _champ_borne(
            "Rayon de pliage général (mm)",
            initiales["Rayon de pliage général (mm)"],
            RAYON_MIN_MM,
            0.5,
            help=(
                "Utilisé pour tout pli sans cote de rayon. Pré-rempli depuis le plan, "
                "sinon depuis le paramètre rayon_pliage_defaut_mm (administrable)."
            ),
        )

    lignes_profil = []
    if piece.profil_pliage:
        for element in piece.profil_pliage.elements:
            if isinstance(element, Aile):
                lignes_profil.append(
                    {"type": "aile", "longueur": element.longueur, "angle": None, "sens": None}
                )
            else:
                lignes_profil.append(
                    {"type": "pli", "longueur": None, "angle": element.angle, "sens": element.sens}
                )
    st.caption("Profil de pliage (une ligne par élément, dans l'ordre)")
    tableau_profil = st.data_editor(
        pd.DataFrame(lignes_profil, columns=["type", "longueur", "angle", "sens"]),
        num_rows="dynamic",
        key="editeur_profil",
        column_config={
            "type": st.column_config.SelectboxColumn(
                "type", options=["aile", "pli"], required=True
            ),
            # « inconnu » inclus : valeur possible de l'extraction — la
            # validation exige ensuite « haut » ou « bas ».
            "sens": st.column_config.SelectboxColumn(
                "sens", options=["haut", "bas", "inconnu"]
            ),
        },
    )

    st.caption("Trous (rond : diamètre ; oblong/carré/rectangulaire : longueur × largeur)")
    tableau_trous = st.data_editor(
        pd.DataFrame(
            [
                {
                    "forme": t.forme,
                    "diametre": t.diametre,
                    "longueur": t.longueur,
                    "largeur": t.largeur,
                    "quantite": t.quantite,
                }
                for t in piece.contours.trous
            ],
            columns=["forme", "diametre", "longueur", "largeur", "quantite"],
        ),
        num_rows="dynamic",
        key="editeur_trous",
        column_config={
            "forme": st.column_config.SelectboxColumn(
                "forme",
                options=["rond", "oblong", "carre", "rectangulaire", "autre"],
                required=True,
            ),
        },
    )

    elements: list[Aile | Pli] = []
    lignes_profil_editees = tableau_profil.to_dict("records")
    lignes_trous_editees = tableau_trous.to_dict("records")
    erreurs = [matiere.explication] if matiere_id is None else []
    erreurs += [
        initiales[libelle].explication
        if initiales[libelle].origine in ("absente", "hors_bornes")
        else f"{libelle} : valeur à saisir."
        for libelle, saisie in zip(initiales, (epaisseur, largeur, rayon_general), strict=True)
        if saisie is None
    ]
    erreurs += _valider_lignes(lignes_profil_editees, lignes_trous_editees)
    if erreurs:
        return None, matiere_id, erreurs

    for ligne in lignes_profil_editees:
        if not any(v is not None and v != "" for v in ligne.values()):
            continue  # ligne vide du data_editor
        if ligne["type"] == "aile":
            elements.append(Aile(longueur=float(ligne["longueur"])))
        else:
            elements.append(Pli(angle=float(ligne["angle"]), sens=ligne["sens"]))
    trous = [
        Trou(
            forme=ligne["forme"] or "rond",
            diametre=_nombre(ligne.get("diametre")),
            longueur=_nombre(ligne.get("longueur")),
            largeur=_nombre(ligne.get("largeur")),
            quantite=int(_nombre(ligne.get("quantite")) or 1),
        )
        for ligne in lignes_trous_editees
        if any(v is not None and v != "" for v in ligne.values())
    ]

    editee = piece.model_copy(deep=True)
    editee.matiere.epaisseur.valeur = epaisseur
    editee.matiere.designation.valeur = matiere_id
    editee.encombrement.largeur.valeur = largeur
    if elements:
        editee.profil_pliage = ProfilPliage(
            cotation=piece.profil_pliage.cotation if piece.profil_pliage else "exterieure",
            rayon_pliage_general=rayon_general,
            elements=elements,
        )
    editee.contours.trous = trous
    return editee, matiere_id, []


def ecran_validation() -> None:
    """Écran 2 : validation humaine — anomalies en tête, 3D, recalcul immédiat."""
    st.title("Validation de la pièce")
    # Bouton unique, rendu en premier : reste accessible quoi qu'il arrive
    # plus bas (extraction échouée, saisie bloquée, erreur imprévue).
    if st.button("Retour au dépôt"):
        revenir_au_depot(st.session_state)
        st.rerun()
    resultat_initial: ResultatDevis = st.session_state[CLE_RESULTAT]
    piece_extraite = resultat_initial.piece
    if piece_extraite is None:
        st.error(resultat_initial.erreur or "Aucune pièce extraite.")
        return
    # Unité du plan avant le formulaire : visible même si la saisie est bloquée.
    if resultat_initial.conversion is not None:
        _afficher_unites(resultat_initial.conversion)
    # La pièce corrigée par l'assistant (acceptations précédentes) fait foi.
    piece: PieceExtraite = st.session_state.get(CLE_PIECE_CORRIGEE) or piece_extraite
    contexte = st.session_state.get(CLE_CONTEXTE, {})

    _ecran_assistant(piece)

    with get_session() as session:
        choix_matieres = _choix_matieres(session)
        traitements = sorted(
            {tid for tid in TRAITEMENT_ID_PAR_TYPE.values() if get_traitement(tid, session)}
        )

        designation = piece.matiere.designation.valeur
        matiere = matiere_initiale(
            contexte.get("matiere_id"),
            designation,
            choix_matieres.values(),
            corrigee=designation != piece_extraite.matiere.designation.valeur,
        )
        editee, matiere_id, erreurs_saisie = _editer_piece(
            piece, choix_matieres, matiere, resultat_initial.conversion
        )
        if editee is None:
            for erreur in erreurs_saisie:
                st.error(f"⛔ Saisie incomplète — {erreur}")
            st.info("Corrigez le formulaire : aucun élément n'est supprimé silencieusement.")
            return

        # --- Anomalies et alertes en tête ------------------------------------
        for probleme in editee.problemes_coherence():
            st.warning(f"⚠️ Cohérence : {probleme}")
        for champ in _champs_peu_surs(editee, session):
            st.warning(f"⚠️ Lecture incertaine — {champ}")

        # --- Recalcul immédiat (chaque modification ré-exécute le script) ----
        resultat = rechiffrer(
            editee, matiere_id, contexte.get("client_id"), contexte.get("quantites"), session
        )
        _afficher_constats(resultat)
        if resultat.erreur:
            st.error(resultat.erreur)
            return

        # --- Modèle 3D + prix provisoire --------------------------------------
        col_3d, col_prix = st.columns(2)
        with col_3d:
            try:
                maillage = construire_modele_3d(editee, float(get_parametre("facteur_k", session)))
                figure = maillage_vers_figure(maillage)
            except ErreurGeometrie:
                figure = None
            if figure is not None:
                st.plotly_chart(figure, width="stretch")
            else:
                st.info("Pas de profil de pliage : modèle 3D non représenté en V1.")
        with col_prix:
            if resultat.chiffrage is not None:
                st.caption("Prix provisoire")
                st.table(
                    {
                        "Quantité": [p.quantite for p in resultat.chiffrage.paliers],
                        "Coût unitaire (€)": [
                            float(formater_valeur("cout_unitaire_eur", p.cout_unitaire_eur))
                            for p in resultat.chiffrage.paliers
                        ],
                        "Prix unitaire (€)": [
                            float(formater_valeur("prix_unitaire_eur", p.prix_unitaire_eur))
                            for p in resultat.chiffrage.paliers
                        ],
                    }
                )

        # --- Origine des coûts --------------------------------------------------
        if resultat.chiffrage is not None:
            with st.expander("D'où viennent les coûts ?"):
                st.caption(
                    "Coût(Q) = Σ coûts variables + Σ coûts fixes ÷ Q "
                    "(finition : max(variable, minimum de lot ÷ Q)) ; "
                    "prix = coût ÷ (1 − marge)."
                )
                st.dataframe(
                    [
                        {
                            "Bloc": ligne["bloc"],
                            "Variable (€/pièce)": float(
                                formater_valeur(
                                    "cout_unitaire_eur", ligne["variable_eur_piece"]
                                )
                            ),
                            "Fixe (€/lot)": float(
                                formater_valeur(
                                    "cout_unitaire_eur", ligne["fixe_eur_lot"]
                                )
                            ),
                            "Détail": ligne["detail"],
                        }
                        for ligne in ventilation_couts(resultat.chiffrage)
                    ],
                    hide_index=True,
                )
                st.caption("Trace complète du calcul (figée au chiffrage) :")
                st.dataframe(lignes_trace(resultat.chiffrage), hide_index=True)

        # --- Option traitement de surface --------------------------------------
        traitement = st.selectbox("Option traitement de surface", ["(aucune)"] + traitements)
        traitement_id = None if traitement == "(aucune)" else traitement

        # --- Validation → Devis -------------------------------------------------
        auteur = st.text_input("Votre nom (auteur des modifications)")
        quantite_commandee = None
        if resultat.chiffrage is not None:
            paliers = [p.quantite for p in resultat.chiffrage.paliers]
            quantite_commandee = st.selectbox("Quantité commandée", paliers)
        if st.button(
            "Valider la pièce",
            disabled=resultat.chiffrage is None or not auteur or quantite_commandee is None,
        ):
            client_id = contexte.get("client_id")
            client = get_client(client_id, session) if client_id else None
            marge = (
                client.marge_specifique
                if client and client.marge_specifique is not None
                else float(get_parametre("marge_defaut", session))
            )
            option = (
                calculer_bloc_finition(editee, resultat.flan, session, traitement_id=traitement_id)
                if traitement_id and resultat.flan
                else None
            )
            devis = Devis(
                id=f"D-{date.today().year}-{uuid.uuid4().hex[:4].upper()}",
                client_id=client_id,
                matiere_id=matiere_id,
                piece_validee=editee,
                chiffrage=resultat.chiffrage,
                flan=resultat.flan,
                marge=marge,
                options=[option] if option else [],
                quantite_commandee=quantite_commandee,
                auteur=auteur,
                date_creation=datetime.now(),
            )
            devis.valider(auteur)
            # Journal des corrections de l'assistant (proposées et leur issue).
            for correction in st.session_state.get(CLE_CORRECTIONS, []):
                devis.modifications.append(
                    Modification(
                        auteur=auteur,
                        date=datetime.now(),
                        champ="correction_ia",
                        avant=correction["texte"],
                        apres=(
                            f"{correction['issue']} "
                            f"({correction['nb_modifications']} modification(s))"
                        ),
                    )
                )
            st.session_state[CLE_DEVIS] = devis
            st.rerun()


# `streamlit run` exécute le script comme __main__ ; le garde-fou permet
# aussi l'import des fonctions pures dans les tests.
if __name__ == "__main__":
    main()
