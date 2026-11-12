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
from generateur_devis.data.acces import get_parametre
from generateur_devis.data.audit import historique
from generateur_devis.data.db import get_session
from generateur_devis.ui.auth import verifier_identifiants
from generateur_devis.ui.consultation import (
    LIBELLES_TABLES,
    colonnes_consultables,
    consulter_referentiel,
)

CLE_PROPOSITION_ADMIN = "proposition_admin"
CLE_AUTEUR = "admin_auteur"
# Résultat de la dernière acceptation (niveau, texte) : affiché au rerun suivant,
# sinon le ``st.rerun()`` qui suit l'application l'efface aussitôt.
CLE_MESSAGE_ADMIN = "message_admin"

# Un F5 ouvre une nouvelle session Streamlit : connexion et proposition perdues (#93).
AVERTISSEMENT_RECHARGEMENT_ADMIN = (
    "Ne rechargez pas la page et n'utilisez pas le retour arrière du navigateur : "
    "la proposition en attente serait perdue et vous seriez déconnecté. "
    "Acceptez-la ou refusez-la d'abord."
)
MESSAGE_AUCUNE_MODIFICATION = "L'agent n'a proposé aucune modification. Reformulez la demande."


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

    # Modèle unique : paramètre administrable (l'agent peut le modifier),
    # invisible ici ; la variable d'environnement MODELE_EXTRACTION le surcharge.
    # Une désignation invalide remonte en ErreurAdmin (message clair).
    with get_session() as session:
        nom_modele = os.environ.get("MODELE_EXTRACTION") or get_parametre(
            "modele_extraction", session
        )

    message = st.session_state.pop(CLE_MESSAGE_ADMIN, None)
    if message is not None:
        niveau, texte_message = message
        if niveau == "succes":
            st.success(texte_message)
        else:
            st.error(texte_message)

    proposition: PropositionAdmin | None = st.session_state.get(CLE_PROPOSITION_ADMIN)
    lignes: list[tuple[str, str, str, str, str]] | None = None

    if proposition is None:
        texte = st.text_area(
            "Mise à jour demandée",
            placeholder="Ex. « le S235JR passe à 1,25 €/kg » ou « ajoute un traitement "
            "galvanisation à 0,60 €/m², minimum de lot 40 € »",
        )
        if st.button(
            "Proposer la modification",
            disabled=not texte.strip(),
        ):
            try:
                with st.spinner("L'agent analyse la demande…"), get_session() as session:
                    proposition = proposer_modifications(texte, nom_modele, session)
                st.session_state[CLE_PROPOSITION_ADMIN] = proposition
                st.rerun()
            except ErreurAdmin as e:
                st.error(str(e))
    elif not proposition.modifications:
        # Demande refusée ou ambiguë : l'agent ne répond que par une remarque.
        # Rien à accepter, donc ni tableau vide ni bouton « Accepter » (#93).
        st.info(f"💬 {proposition.remarque or MESSAGE_AUCUNE_MODIFICATION}")
        if st.button("Nouvelle demande"):
            st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
            st.rerun()
    else:
        # --- Affichage avant / après (valeur actuelle lue en base) --------------
        try:
            with get_session() as session:
                lignes = proposition.ligne_avant_apres(session)
        except ErreurAdmin as e:
            # Ligne disparue ou clé devenue invalide depuis la proposition :
            # sans capture, l'écran planterait à chaque rerun (#98).
            st.error(f"Cette proposition ne correspond plus à la base : {e} Refaites la demande.")
            if st.button("Nouvelle demande"):
                st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
                st.rerun()
    if proposition is not None and lignes is not None:
        st.caption("⚠️ " + AVERTISSEMENT_RECHARGEMENT_ADMIN)
        if proposition.remarque:
            st.info(f"💬 {proposition.remarque}")
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
                    st.session_state[CLE_MESSAGE_ADMIN] = (
                        "succes",
                        f"{nb} modification(s) appliquée(s) et auditée(s).",
                    )
                except ErreurAdmin as e:
                    st.session_state[CLE_MESSAGE_ADMIN] = (
                        "erreur",
                        f"Modification refusée à l'application : {e}",
                    )
                st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
                st.rerun()
        with col_non:
            if st.button("❌ Refuser"):
                st.session_state.pop(CLE_PROPOSITION_ADMIN, None)
                st.rerun()

    # --- Consultation des référentiels (lecture seule, sans IA, #94) -----------
    with st.expander("🔎 Consulter les référentiels"):
        table = st.selectbox(
            "Table",
            list(LIBELLES_TABLES),
            format_func=LIBELLES_TABLES.get,
            key="consultation_table",
        )
        with get_session() as session:
            lignes_ref = consulter_referentiel(table, session)
        if lignes_ref:
            st.dataframe(
                pd.DataFrame(lignes_ref, columns=colonnes_consultables(table)),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Aucune ligne dans cette table.")

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
