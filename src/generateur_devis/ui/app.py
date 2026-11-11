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
from generateur_devis.devis import Devis
from generateur_devis.modele3d import ErreurGeometrie, construire_modele_3d
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui.pipeline import ResultatDevis, orchestrer_devis, rechiffrer
from generateur_devis.ui.rendu3d import maillage_vers_figure

TYPES_PLAN = ["pdf", "png", "jpg", "jpeg", "webp"]
CLE_RESULTAT = "resultat_devis"
CLE_DEVIS = "devis"
CLE_CONTEXTE = "contexte"
SEUIL_CONFIANCE = 0.7


def main() -> None:
    if st.session_state.get(CLE_DEVIS) is not None:
        devis: Devis = st.session_state[CLE_DEVIS]
        st.success(f"Pièce validée — devis {devis.id} prêt pour l'émission (étape suivante).")
        if st.button("Nouveau devis"):
            st.session_state.pop(CLE_RESULTAT, None)
            st.session_state.pop(CLE_DEVIS, None)
            st.rerun()
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
        nom_modele = st.text_input("Modèle d'extraction", os.environ.get("MODELE_EXTRACTION", ""))

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
        st.session_state[CLE_CONTEXTE] = {"client_id": client_id, "quantites": quantites}
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


def _champs_peu_surs(piece: PieceExtraite) -> list[str]:
    """Champs du parcours lus avec une confiance sous le seuil (anomalies en tête)."""
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
        if champ.confiance is not None and champ.confiance < SEUIL_CONFIANCE
    ]


def _editer_piece(piece: PieceExtraite, matieres: list[str]) -> tuple[PieceExtraite, str]:
    """Formulaire borné V1 : matière, épaisseur, largeur, profil de pliage, trous.

    Retourne la pièce reconstruite et la matière choisie. Streamlit ré-exécute
    le script à chaque modification : le recalcul est donc immédiat (§4).
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
    for ligne in tableau_profil.to_dict("records"):
        if ligne["type"] == "aile" and ligne["longueur"]:
            elements.append(Aile(longueur=float(ligne["longueur"])))
        elif ligne["type"] == "pli" and ligne["angle"]:
            elements.append(Pli(angle=float(ligne["angle"]), sens=ligne["sens"] or "haut"))
    trous = [
        Trou(
            forme=ligne["forme"] or "rond",
            diametre=float(ligne["diametre"]),
            quantite=int(ligne["quantite"]),
        )
        for ligne in tableau_trous.to_dict("records")
        if ligne["diametre"]
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
    return editee, matiere_id


def ecran_validation() -> None:
    """Écran 2 : validation humaine — anomalies en tête, 3D, recalcul immédiat."""
    st.title("Validation de la pièce")
    resultat_initial: ResultatDevis = st.session_state[CLE_RESULTAT]
    piece = resultat_initial.piece
    if piece is None:
        st.error(resultat_initial.erreur or "Aucune pièce extraite.")
        if st.button("Retour au dépôt"):
            st.session_state.pop(CLE_RESULTAT, None)
            st.rerun()
        return
    contexte = st.session_state.get(CLE_CONTEXTE, {})

    with get_session() as session:
        matieres = [m.id for m in list_matieres(session)]
        traitements = sorted(
            {tid for tid in TRAITEMENT_ID_PAR_TYPE.values() if get_traitement(tid, session)}
        )

        editee, matiere_id = _editer_piece(piece, matieres)

        # --- Anomalies et alertes en tête ------------------------------------
        for probleme in editee.problemes_coherence():
            st.warning(f"⚠️ Cohérence : {probleme}")
        for champ in _champs_peu_surs(editee):
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
                            round(p.cout_unitaire_eur, 2) for p in resultat.chiffrage.paliers
                        ],
                        "Prix unitaire (€)": [
                            round(p.prix_unitaire_eur, 2) for p in resultat.chiffrage.paliers
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
            st.session_state[CLE_DEVIS] = devis
            st.rerun()


# Streamlit exécute le module au premier niveau à chaque interaction.
main()
