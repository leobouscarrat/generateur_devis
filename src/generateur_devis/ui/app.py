"""Interface Streamlit du parcours devis (étapes 1 et 4, issues #23 et #24).

Lancement : ``uv run streamlit run src/generateur_devis/ui/app.py``.

Écran unique conditionné par ``st.session_state`` (YAGNI V1) : dépôt du plan
tant qu'il n'y a pas de résultat, validation humaine ensuite. Couche de
présentation **fine** : tout le calcul est dans ``ui.pipeline`` ; le rendu 3D
est dans ``ui.rendu3d``.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from generateur_devis.calcul_prix import calculer_bloc_finition
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

TYPES_PLAN = ["pdf", "png", "jpg", "jpeg", "webp"]
CLE_RESULTAT = "resultat_devis"
CLE_DEVIS = "devis"
CLE_CONTEXTE = "contexte"
CLE_PIECE_CORRIGEE = "piece_corrigee"
CLE_PROPOSITION = "proposition_correction"
CLE_CORRECTIONS = "corrections_ia"


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
    resultat_initial: ResultatDevis | None = st.session_state.get(CLE_RESULTAT)
    if resultat_initial:
        for alerte in resultat_initial.alertes_controles:
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
            resultat: ResultatDevis | None = st.session_state.get(CLE_RESULTAT)
            if resultat is None or resultat.flan is None:
                st.error("Flan introuvable — réanalysez le plan avant émission.")
                return
            with get_session() as session:
                emettre(devis, resultat.flan, devis.auteur or "inconnu", session)
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
        matieres = [m.id for m in list_matieres(session)]
        paliers = [str(q) for q in get_parametre("paliers_quantite", session)]

    col1, col2 = st.columns(2)
    with col1:
        nom_client = st.selectbox("Client", ["(sans)"] + list(choix_clients))
        client_id = choix_clients.get(nom_client)
        matiere = st.selectbox("Matière (si absente du plan)", ["(à extraire)"] + matieres)
        matiere_id = None if matiere == "(à extraire)" else matiere
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
        st.session_state[CLE_RESULTAT] = resultat
        st.session_state[CLE_CONTEXTE] = {
            "client_id": client_id,
            "quantites": quantites,
            "nom_modele": nom_modele,
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
            ligne.get("longueur"),
            ligne.get("angle"),
            ligne.get("sens"),
        )
        if type_ == "aile":
            if not longueur or float(longueur) <= 0:
                erreurs.append(f"Profil ligne {i} : aile sans longueur valide.")
        elif type_ == "pli":
            if angle is None or angle == "":
                erreurs.append(f"Profil ligne {i} : pli sans angle.")
            if sens not in ("haut", "bas"):
                erreurs.append(f"Profil ligne {i} : sens du pli « haut » ou « bas » attendu.")
        else:
            erreurs.append(f"Profil ligne {i} : type « aile » ou « pli » attendu, reçu {type_!r}.")
    for i, ligne in enumerate(lignes_trous, start=1):
        remplie = any(v is not None and v != "" for v in ligne.values())
        if not remplie:
            continue
        if not ligne.get("diametre") or float(ligne["diametre"]) <= 0:
            erreurs.append(f"Trou ligne {i} : diamètre manquant ou invalide.")
        if not ligne.get("quantite") or int(ligne["quantite"]) < 1:
            erreurs.append(f"Trou ligne {i} : quantité ≥ 1 attendue.")
    return erreurs


def _editer_piece(
    piece: PieceExtraite, matieres: list[str]
) -> tuple[PieceExtraite | None, str, list[str]]:
    """Formulaire borné V1 : matière, épaisseur, largeur, profil de pliage, trous.

    Retourne la pièce reconstruite, la matière choisie et les erreurs de
    saisie. En cas d'erreur, la pièce est None : pas de recalcul sur un
    formulaire incomplet (jamais de suppression silencieuse d'un élément).
    Streamlit ré-exécute le script à chaque modification : le recalcul est
    donc immédiat (§4).
    """
    col1, col2, col3 = st.columns(3)
    with col1:
        matiere_defaut = piece.matiere.designation.valeur
        index = matieres.index(matiere_defaut) if matiere_defaut in matieres else 0
        matiere_id = st.selectbox("Matière", matieres, index=index)
    with col2:
        epaisseur = st.number_input(
            "Épaisseur (mm)",
            min_value=0.1,
            value=float(piece.matiere.epaisseur.valeur or 1.0),
            step=0.5,
        )
    with col3:
        largeur = st.number_input(
            "Largeur d'encombrement (mm)",
            min_value=1.0,
            value=float(piece.encombrement.largeur.valeur or 50.0),
            step=5.0,
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
    )

    st.caption("Trous")
    tableau_trous = st.data_editor(
        pd.DataFrame(
            [
                {"forme": t.forme, "diametre": t.diametre, "quantite": t.quantite}
                for t in piece.contours.trous
            ],
            columns=["forme", "diametre", "quantite"],
        ),
        num_rows="dynamic",
        key="editeur_trous",
    )

    elements: list[Aile | Pli] = []
    lignes_profil_editees = tableau_profil.to_dict("records")
    lignes_trous_editees = tableau_trous.to_dict("records")
    erreurs = _valider_lignes(lignes_profil_editees, lignes_trous_editees)
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
            diametre=float(ligne["diametre"]),
            quantite=int(ligne["quantite"]),
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
            rayon_pliage_general=(
                piece.profil_pliage.rayon_pliage_general if piece.profil_pliage else None
            ),
            elements=elements,
        )
    editee.contours.trous = trous
    return editee, matiere_id, []


def ecran_validation() -> None:
    """Écran 2 : validation humaine — anomalies en tête, 3D, recalcul immédiat."""
    st.title("Validation de la pièce")
    resultat_initial: ResultatDevis = st.session_state[CLE_RESULTAT]
    piece_extraite = resultat_initial.piece
    if piece_extraite is None:
        st.error(resultat_initial.erreur or "Aucune pièce extraite.")
        if st.button("Retour au dépôt"):
            st.session_state.pop(CLE_RESULTAT, None)
            st.rerun()
        return
    # La pièce corrigée par l'assistant (acceptations précédentes) fait foi.
    piece: PieceExtraite = st.session_state.get(CLE_PIECE_CORRIGEE) or piece_extraite
    contexte = st.session_state.get(CLE_CONTEXTE, {})

    _ecran_assistant(piece)

    with get_session() as session:
        matieres = [m.id for m in list_matieres(session)]
        traitements = sorted(
            {tid for tid in TRAITEMENT_ID_PAR_TYPE.values() if get_traitement(tid, session)}
        )

        editee, matiere_id, erreurs_saisie = _editer_piece(piece, matieres)
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
