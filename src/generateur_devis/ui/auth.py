"""Connexion de démonstration pour l'écran d'administration (issue #38).

**Cosmétique de démo, pas une sécurité réelle** : toute protection Streamlit
côté client est contournable (le code est lisible). Elle sert à matérialiser
les rôles du §12 et à rattacher un auteur à chaque modification d'audit.

Comptes : ``st.secrets["admin"]["utilisateurs"]`` (dict nom → mot de passe).
"""

from __future__ import annotations

import hmac


def verifier_identifiants(nom: str, mot_de_passe: str, comptes: dict[str, str]) -> bool:
    """Vérifie un couple nom / mot de passe contre les comptes déclarés.

    Comparaison en temps constant pour éviter les attaques par timing
    (cosmétique, mais autant prendre la bonne habitude).
    """
    attendu = comptes.get(nom)
    if attendu is None:
        return False
    return hmac.compare_digest(mot_de_passe, attendu)
