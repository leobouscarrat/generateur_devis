"""Écran de dépôt du plan et contexte commercial (issue #23, étape 1).

Lancement : ``uv run streamlit run src/generateur_devis/ui/app.py``.

Couche de présentation **fine** : tout le calcul est dans
``ui.pipeline.orchestrer_devis`` ; cet écran collecte les entrées, affiche
les erreurs métier lisiblement et stocke le `ResultatDevis` dans
``st.session_state`` pour l'écran de validation (4.3).
"""

from __future__ import annotations

import os

import streamlit as st

from generateur_devis.data.acces import get_parametre, list_clients, list_matieres
from generateur_devis.data.db import get_session
from generateur_devis.ui.pipeline import ResultatDevis, orchestrer_devis

TYPES_PLAN = ["pdf", "png", "jpg", "jpeg", "webp"]
CLE_RESULTAT = "resultat_devis"


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
        try:
            quantites = [int(q.strip()) for q in saisie.split(",") if q.strip()]
            if not quantites or any(q <= 0 for q in quantites):
                raise ValueError
        except ValueError:
            st.error("Quantités invalides : entiers positifs séparés par des virgules.")
            return st.session_state.get(CLE_RESULTAT)
        nom_modele = st.text_input("Modèle d'extraction", os.environ.get("MODELE_EXTRACTION", ""))

    if st.button("Lancer l'analyse", disabled=plan is None or not nom_modele):
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

    resultat = st.session_state.get(CLE_RESULTAT)
    if resultat is None:
        return None
    if resultat.erreur:
        st.error(resultat.erreur)
    else:
        _afficher_synthese(resultat)
    return resultat


def _afficher_synthese(resultat: ResultatDevis) -> None:
    """Synthèse du résultat provisoire (le formulaire complet arrive en 4.3)."""
    blocages = [c for c in resultat.constats if c.severite == "blocage"]
    alertes = [c for c in resultat.constats if c.severite == "alerte"] + resultat.alertes_controles
    for constat in blocages:
        st.error(f"⛔ {constat.regle} — {constat.message}")
    for constat in alertes:
        st.warning(f"⚠️ {constat.regle} — {constat.message}")

    if resultat.chiffrage is not None:
        st.success("Analyse terminée — chiffrage provisoire disponible.")
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
    elif resultat.piece is not None and not blocages:
        st.info("Pièce extraite — matière à préciser pour chiffrer (écran de validation).")


# Streamlit exécute le module au premier niveau à chaque interaction.
ecran_depot()
