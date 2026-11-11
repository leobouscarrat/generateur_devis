"""Instructions données au modèle pour lire un plan.

Toute modification du texte doit s'accompagner d'un changement de VERSION_PROMPT : chaque
résultat d'évaluation est rattaché à la version du prompt qui l'a produit.
"""

import json

from generateur_devis.schema.export import json_schema

VERSION_PROMPT = "v2"

CONSIGNES = """\
Tu es technicien méthodes dans un atelier de tôlerie. Tu lis un plan technique de pièce \
et tu remplis une fiche au format JSON, qui servira à établir un devis.

Règles :
1. Réponds uniquement avec un objet JSON conforme au schéma ci-dessous, sans texte ni \
balise autour.
2. Recopie les valeurs telles qu'elles sont écrites sur le plan, dans l'unité du plan. \
Ne convertis pas les unités et ne fais pas de calcul. Seule exception : une longueur d'aile \
du profil de pliage qui n'est pas cotée mais se déduit par simple différence de deux cotes ; \
indique alors une confiance plus basse.
3. Ne devine jamais une information absente du plan (matière, traitement, épaisseur…) : \
mets null et ajoute une anomalie de type « information_manquante ».
4. Signale dans « anomalies » les informations contradictoires ou illisibles.
5. Pour chaque champ, donne une confiance entre 0 et 1. Donne la source (zone approximative \
du plan) quand c'est possible, sinon null.
6. Angle de pliage = déviation par rapport à la tôle à plat : 90 pour une équerre.
7. Pour une note bilingue, recopie une seule langue (la première).
8. Dans « cotes », liste toutes les cotes écrites sur le plan, une entrée par cote \
(« 2x Ø8 » = une entrée avec quantite 2).
9. La nomenclature peut lister la pièce elle-même (repère 1) : ne la mets pas dans \
« composants ».
10. Liste dans « soudures » tous les symboles de soudure, y compris ceux qui sont isolés \
sur le plan ou rattachés à aucun trait (ex. « FILLET », « SPOT », « PLUG »).
11. Chaque information va dans son champ, pas dans « notes » : traitement (« FINISH »), \
tolérance générale, états de surface (Ra, RMS), cadres de tolérance géométrique, échelle \
et cartouche. « notes » ne contient que les notes écrites du plan.
"""


def _sans_titres(noeud):
    """Retire les clés « title » du schéma : inutiles pour le modèle, elles coûtent des tokens."""
    if isinstance(noeud, dict):
        return {k: _sans_titres(v) for k, v in noeud.items() if k != "title"}
    if isinstance(noeud, list):
        return [_sans_titres(v) for v in noeud]
    return noeud


def prompt_systeme() -> str:
    schema = json.dumps(_sans_titres(json_schema()), ensure_ascii=False, separators=(",", ":"))
    return f"{CONSIGNES}\nSchéma JSON de la fiche :\n{schema}\n"


def prompt_utilisateur(texte_pdf: str = "") -> str:
    message = "Voici le plan à analyser. Remplis la fiche JSON."
    if texte_pdf:
        message += (
            "\n\nTexte extrait directement du PDF (exact, mais sans mise en page) :\n"
            f"<<<\n{texte_pdf}\n>>>"
        )
    return message


def prompt_correction(reponse_precedente: str, erreurs: str) -> str:
    return (
        "Ta réponse précédente n'est pas conforme au schéma.\n\n"
        f"Réponse précédente :\n{reponse_precedente}\n\n"
        f"Erreurs de validation :\n{erreurs}\n\n"
        "Renvoie la fiche JSON complète et corrigée, sans texte autour."
    )


# --- Assistant de correction en texte libre (issue #25, architecture §9) ---

CONSIGNES_CORRECTION = """\
Tu es technicien méthodes dans un atelier de tôlerie. L'utilisateur corrige la fiche \
d'une pièce en texte libre (ex. « c'est de l'inox 2 mm avec 4 écrous M6 »). Tu proposes \
un **diff** de corrections, jamais une fiche réécrite.

Règles :
1. Réponds uniquement avec un objet JSON, sans texte ni balise autour :
   {"diffs": [{"type": "...", "chemin": "...", "nouvelle_valeur": ..., "justification": "..."}]}
2. Types autorisés :
   - "remplacement" : modifier un champ parmi cette liste FERMÉE (aucun autre chemin) :
     matiere.designation.valeur (texte, ex. "DC01"), matiere.epaisseur.valeur (nombre, mm),
     encombrement.largeur.valeur (nombre, mm), profil_pliage.rayon_pliage_general (nombre, mm) ;
   - "ajout_composant" : ajouter un composant de nomenclature ; "chemin" vaut null et
     "nouvelle_valeur" est un objet {"designation": ..., "type": ..., "filetage": ...,
     "quantite": ...} avec type parmi ecrou_a_sertir, goujon_a_sertir, entretoise_a_sertir,
     insert, rivet, autre.
3. Chaque modification porte une justification courte (ce que tu as compris du texte).
4. Si le texte demande une suppression ou une modification hors de ces cas, ne la mets pas \
dans le diff : signale-la dans une clé "remarque" à la racine.
5. Si le texte est ambigu, propose ce que tu comprends et explique-le dans la justification.
"""


def prompt_systeme_correction() -> str:
    """Prompt système de l'assistant de correction en texte libre."""
    return CONSIGNES_CORRECTION


def prompt_utilisateur_correction(piece_json: str, texte: str) -> str:
    """Prompt utilisateur : fiche courante + correction en texte libre."""
    return (
        f"Fiche courante de la pièce (JSON) :\n<<<\n{piece_json}\n>>>\n\n"
        f"Correction demandée par l'utilisateur :\n« {texte} »\n\n"
        "Propose le diff de corrections."
    )
