"""Écran Streamlit d'administration des référentiels (issue #34, §12).

Séparé du parcours devis. Lancement : ``uv run streamlit run
src/generateur_devis/ui/admin.py``.

L'agent propose un diff borné (jamais d'écriture directe) ; l'affichage
avant/après lit la valeur actuelle en base ; l'acceptation explicite écrit
et audite (daté, attribué) ; le refus n'écrit rien. Couche de présentation
fine : toute la logique est dans ``admin_agent`` et ``data.audit``.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from generateur_devis.admin_agent import (
    ErreurAdmin,
    PropositionAdmin,
    proposer_modifications,
)
from generateur_devis.data.audit import historique
from generateur_devis.data.db import get_session
from generateur_devis.ui.auth import verifier_identifiants

CLE_PROPOSITION_ADMIN = "proposition_admin"
CLE_AUTEUR = "admin_auteur"


def _comptes() -> dict[str, str]:
    """Comptes déclarés dans les secrets : ``[admin.utilisateurs]`` nom = mdp."""
    return dict(st.secrets.get("admin", {}).get("utilisateurs", {}))


def _ecran_connexion() -> bool:
    """Porte de connexion (démo — pas une sécurité réelle).

    Returns:
        True si connecté ; le nom de connexion est en
        ``session_state[CLE_AUTEUR]`` et devient l'auteur de l'audit.
    """
    if st.session_state.get(CLE_AUTEUR):
        return True
    comptes = _comptes()
    if not comptes:
        st.error(
            "Aucun compte configuré — déclarez les utilisateurs dans "
            "`.streamlit/secrets.toml` (voir README § Administration)."
        )
        return False
    st.title("Connexion — Administration")
    with st.form("connexion"):
        nom = st.text_input("Nom")
        mot_de_passe = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            if verifier_identifiants(nom, mot_de_passe, comptes):
                st.session_state[CLE_AUTEUR] = nom
                st.rerun()
            else:
                st.error("Identifiants incorrects.")
    return False


def main() -> None:
    if not _ecran_connexion():
        return
    auteur = st.session_state[CLE_AUTEUR]

    st.title("Administration des référentiels")
    st.caption(
        f"Connecté : **{auteur}** — décrivez la mise à jour en texte libre, "
        "l'agent propose un diff, vous validez explicitement. "
        "Toute modification est datée et attribuée."
    )
    if st.button("Se déconnecter"):
        st.session_state.pop(CLE_AUTEUR, None)
        st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
        st.rerun()

    nom_modele = st.text_input("Modèle de l'agent", os.environ.get("MODELE_EXTRACTION", ""))

    proposition: PropositionAdmin | None = st.session_state.get(CLE_PROPOSITION_ADMIN)

    if proposition is None:
        texte = st.text_area(
            "Mise à jour demandée",
            placeholder="Ex. « le S235JR passe à 1,25 €/kg » ou « ajoute un traitement "
            "galvanisation à 0,60 €/m², minimum de lot 40 € »",
        )
        if st.button(
            "Proposer la modification",
            disabled=not nom_modele or not texte.strip(),
        ):
            try:
                with st.spinner("L'agent analyse la demande…"), get_session() as session:
                    proposition = proposer_modifications(texte, nom_modele, session)
                st.session_state[CLE_PROPOSITION_ADMIN] = proposition
                st.rerun()
            except ErreurAdmin as e:
                st.error(str(e))
    else:
        # --- Affichage avant / après (valeur actuelle lue en base) --------------
        if proposition.remarque:
            st.info(f"💬 {proposition.remarque}")
        with get_session() as session:
            lignes = proposition.ligne_avant_apres(session)
        st.dataframe(
            pd.DataFrame(
                [
                    {"table": t, "ligne": lig, "champ": c, "avant": a, "après": b}
                    for t, lig, c, a, b in lignes
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        for modif, (_, _, _, _, _) in zip(proposition.modifications, lignes, strict=True):
            if modif.justification:
                st.caption(f"• {modif.justification}")

        col_ok, col_non = st.columns(2)
        with col_ok:
            if st.button("✅ Accepter et appliquer", type="primary"):
                try:
                    with get_session() as session:
                        nb = proposition.appliquer(auteur, session)
                        session.commit()
                    st.success(f"{nb} modification(s) appliquée(s) et auditée(s).")
                except ErreurAdmin as e:
                    st.error(f"Modification refusée à l'application : {e}")
                st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
                st.rerun()
        with col_non:
            if st.button("❌ Refuser"):
                st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
                st.rerun()

    # --- Historique des modifications (daté et attribué, §12) -------------------
    with st.expander("📜 Historique des modifications"):
        with get_session() as session:
            lignes_audit = historique(session)[:50]
        if lignes_audit:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "date": a.date.strftime("%d/%m/%Y %H:%M"),
                            "auteur": a.auteur,
                            "table": a.table_nom,
                            "ligne": a.ligne_id,
                            "champ": a.champ,
                            "avant": a.valeur_avant,
                            "après": a.valeur_apres,
                        }
                        for a in lignes_audit
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.write("Aucune modification enregistrée.")


if __name__ == "__main__":
    main()
