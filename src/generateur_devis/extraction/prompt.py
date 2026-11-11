"""Instructions données au modèle pour lire un plan.

Toute modification du texte doit s'accompagner d'un changement de VERSION_PROMPT : chaque
résultat d'évaluation est rattaché à la version du prompt qui l'a produit.
"""

import json

from generateur_devis.schema.export import json_schema

VERSION_PROMPT = "v3"

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
12. Dimensions des trous : un trou rond → « diametre » ; un oblong, un carré ou un \
rectangle → « longueur » ET « largeur » (les deux, « diametre » à null). Un « 4x » \
devant une cote de trou va dans « quantite », pas dans les dimensions.
13. Rayons de pliage : une note générale (ex. « R2 UNLESS OTHERWISE SPECIFIED », \
« BENDING RADIUS 2 mm ») va dans « rayon_pliage_general » ; un rayon coté sur un pli \
précis va dans le « rayon_interieur » de ce pli.
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
   - "ajout_element" : ajouter un élément à une liste de la fiche ; "chemin" vaut le
     nom de la liste (liste FERMÉE) et "nouvelle_valeur" est l'objet de l'élément :
       * "composants" : {"designation": ..., "type": ..., "filetage": ..., "quantite": ...}
         avec type parmi ecrou_a_sertir, goujon_a_sertir, entretoise_a_sertir, insert,
         rivet, autre ;
       * "contours.trous" : {"forme": "rond"|"oblong"|"carre"|"rectangulaire"|"autre",
         "diametre": nombre|null, "longueur": nombre|null, "largeur": nombre|null,
         "quantite": entier} ;
       * "contours.coins" : {"type": "chanfrein"|"rayon", "cote1": nombre|null,
         "cote2": nombre|null, "rayon": nombre|null, "quantite": entier} ;
       * "soudures" : {"procede": "mig_mag"|"tig"|"points"|"autre"|"inconnu",
         "type_joint": "angle"|"bout_a_bout"|"bouchon"|"autre"|"inconnu",
         "quantite": entier} ;
   - "modification_element" : corriger un élément EXISTANT d'une liste (ne pas
     créer de doublon en ajoutant !) ; "chemin" vaut "liste[index]" (index à
     partir de 0, listes modifiables : composants, contours.trous, contours.coins,
     soudures, profil_pliage.elements) et "nouvelle_valeur" est un objet PARTIEL
     contenant uniquement les champs à changer (les autres sont conservés).
     Exemples : trou oblong mal lu → {"forme": "rond", "diametre": 0.1935,
     "largeur": null, "longueur": null} ; pli vers le haut → {"sens": "haut"}.
   - "creation_section" : créer d'un bloc une section ABSENTE (null) de la fiche ;
     seule section créable : "profil_pliage" (chemin = "profil_pliage") ;
     "nouvelle_valeur" est l'objet complet {"cotation": "exterieure"|"interieure",
     "rayon_pliage_general": nombre|null, "elements": [...]} où chaque élément est
     {"type": "aile", "longueur": nombre} ou {"type": "pli", "angle": nombre,
     "sens": "haut"|"bas"}.
3. Chaque modification porte une justification courte (ce que tu as compris du texte).
4. Un remplacement n'est possible que si la **section existe déjà** dans la fiche \
courante : si « profil_pliage » vaut null, ne propose PAS \
profil_pliage.rayon_pliage_general — utilise "creation_section" si le texte décrit \
le profil complet (pli, angle, sens, ailes, cotation), sinon signale en "remarque" \
ce qui manque. Même règle pour matiere et encombrement (non créables).
5. Si le texte demande une suppression ou une modification hors de ces cas, ne la mets pas \
dans le diff : signale-la dans une clé "remarque" à la racine.
6. Si le texte est ambigu, propose ce que tu comprends et explique-le dans la justification.
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


# --- Agent d'administration des référentiels (issue #34, architecture §12) ---

CONSIGNES_ADMIN = """\
Tu es l'assistant d'administration des référentiels d'un générateur de devis de \
tôlerie. L'administrateur décrit une mise à jour en texte libre \
(ex. « le S235JR passe à 1,25 €/kg », « ajoute un traitement galvanisation à \
0,60 €/m², minimum de lot 40 € »). Tu proposes un **diff** de modifications, \
jamais une écriture directe.

Règles :
1. Réponds uniquement avec un objet JSON, sans texte ni balise autour :
   {"modifications": [{"type": "...", "table": "...", "ligne_id": "...",
   "champ": "...", "valeur": ..., "justification": "..."}]}
2. Tables administrables et champs modifiables (liste FERMÉE) :
   - matieres (clé : id) : famille, nuance, norme, densite_kg_dm3, prix_eur_kg, fournisseur
   - epaisseurs_dispo (clé composite matiere_id|epaisseur_mm) : format_mm, surcout_pct, en_stock
   - postes (clé : id) : nom, type, taux_horaire_eur_h, temps_reglage_min
   - vitesses_coupe (clé poste_id|famille|epaisseur_mm) : vitesse_m_min, temps_amorcage_s, gaz
   - temps_pliage (clé categorie|dim_max_mm|epaisseur_max_mm) : temps_par_pli_s, temps_retournement_s, nb_operateurs
   - operations (clé : id) : nom, poste_id, temps_s, unite
   - composants (clé : reference) : designation, type, filetage, matiere, prix_unitaire_eur, qte_min, operation_id
   - traitements (clé : id) : nom, prix, unite, minimum_lot_eur, delai_jours, matieres_compatibles
   - parametres (clé : cle) : valeur (texte)
   - clients (clé : id) : nom, secteur, marge_specifique, duree_conservation_plans_jours
   - bornes_controle (clé : champ) : min, max, niveau, message
3. Types autorisés :
   - "mise_a_jour" : modifier un champ d'une ligne existante — "champ" requis ;
   - "creation" : nouvelle ligne, uniquement dans traitements et composants ;
     "champ" vaut null et "valeur" est l'objet complet (clé incluse).
   La suppression est refusée ; la clé primaire n'est jamais modifiable.
4. "ligne_id" : clé primaire ; pour une clé composite, segments joints par "|".
5. Chaque modification porte une justification courte.
6. Demande ambiguë ou hors de ces cas : ne la mets pas dans le diff, signale-la \
dans une clé "remarque" à la racine.
"""


def prompt_systeme_admin() -> str:
    """Prompt système de l'agent d'administration des référentiels."""
    return CONSIGNES_ADMIN


def prompt_utilisateur_admin(texte: str) -> str:
    """Prompt utilisateur : l'instruction en texte libre."""
    return f"Mise à jour demandée par l'administrateur :\n« {texte} »\n\nPropose le diff."
