# Architecture — Générateur de devis tôlerie

Ce document décrit l'architecture fonctionnelle et technique de l'outil : le parcours utilisateur, les services, les flux de données, la gestion des erreurs, ainsi que la traçabilité et la confidentialité.

Il s'appuie sur :
- [logique_metier.md](logique_metier.md) : les formules de chiffrage (6 blocs de coût) ;
- [sources_donnees.md](sources_donnees.md) : les tables de référence utilisées par le calcul.

> Les schémas sont écrits en [Mermaid](https://mermaid.js.org/) : ils s'affichent sur GitHub et dans la plupart des éditeurs (extension « Markdown Preview Mermaid Support » pour VS Code), et se modifient directement dans le texte.

---

## Sommaire

1. [Principes directeurs](#1-principes-directeurs)
2. [Parcours utilisateur](#2-parcours-utilisateur)
3. [Détail des étapes](#3-détail-des-étapes)
4. [Boucle de validation](#4-boucle-de-validation)
5. [Services techniques](#5-services-techniques)
6. [Flux de données](#6-flux-de-données)
7. [Cycle de vie d'un devis](#7-cycle-de-vie-dun-devis)
8. [Modèle de données](#8-modèle-de-données)
9. [Intégration de l'IA](#9-intégration-de-lia)
10. [Gestion des erreurs](#10-gestion-des-erreurs)
11. [Traçabilité et confidentialité](#11-traçabilité-et-confidentialité)
12. [Administration](#12-administration)
13. [Stack technique proposée](#13-stack-technique-proposée)
14. [Périmètre V1 / V2](#14-périmètre-v1--v2)
15. [Évaluation de l'extraction](#15-évaluation-de-lextraction)
16. [Décisions et points ouverts](#16-décisions-et-points-ouverts)

---

## 1. Principes directeurs

| # | Principe | Conséquence |
|---|---|---|
| 1 | **L'IA lit, le code calcule** | L'IA extrait des données brutes du plan. Toute géométrie (développé, longueur de coupe, masse) et tout prix sont calculés par du code déterministe. |
| 2 | **L'humain valide** | Aucun devis n'est émis sans validation des données extraites par un chargé d'affaires. |
| 3 | **Le formulaire est la référence unique** | Toutes les corrections (saisie directe ou texte libre) passent par le formulaire structuré. |
| 4 | **Aucune valeur en dur** | Prix, temps, taux et règles viennent des tables de référence, modifiables sans développeur. |
| 5 | **Tout est traçable** | Chaque devis garde l'extraction brute, les corrections, les valeurs finales et les prix figés au moment de l'émission. |
| 6 | **Confidentialité dès la conception** | Les plans clients sont séparés des données résumées et ont une durée de conservation définie par client. |

---

## 2. Parcours utilisateur

```mermaid
flowchart TD
    subgraph P["Parcours du chargé d'affaires"]
        E1["1. Dépôt du plan<br/>+ contexte commercial"]
        E2["2. Extraction<br/>(IA)"]
        E3["3. Géométrie<br/>& faisabilité"]
        E4["4. Validation humaine"]
        E5["5. Chiffrage"]
        E6["6. Restitution<br/>vue interne / vue client"]
        OUT["Devis PDF<br/>+ historique"]

        E1 --> E2 --> E3 --> E4
        E4 -- "modification" --> E3
        E3 -. "prix provisoire" .-> E5
        E4 -- "validé" --> E5
        E5 --> E6
        E6 -- "marge, options,<br/>quantités" --> E5
        E6 -- "émission" --> OUT
    end

    subgraph A["Administration (en parallèle)"]
        R1["Référentiels de coût<br/>matières, postes, temps…"]
        R2["Règles de faisabilité"]
        R3["Clients<br/>& conservation"]
    end

    R2 -.-> E3
    R1 -.-> E5
    R3 -.-> E2
    R3 -.-> OUT
```

Lecture :
- Les étapes 3 et 5 sont **recalculées à chaque modification** à l'étape 4. Elles sont rapides (moins d'une seconde) car entièrement déterministes.
- Le prix est affiché comme **provisoire** pendant la validation, puis **figé** une fois la pièce validée.
- L'administration n'est pas une étape du parcours : elle est utilisée par d'autres personnes (acheteur, bureau des méthodes, contrôle de gestion) et alimente les étapes en données.

---

## 3. Détail des étapes

### Étape 1 — Dépôt du plan et contexte commercial

| | |
|---|---|
| **Entrées** | PDF (vectoriel ou scanné), image (PNG, JPG), photo prise depuis une tablette ou un téléphone |
| **Contexte saisi** | Client, quantités souhaitées (paliers), délai, matière et traitement **si absents du plan** |
| **Traitements** | Détection du type de PDF (texte lisible ou non), conversion en image haute résolution, redressement et contrôle de netteté des photos |
| **Sorties** | Fichier stocké, images des pages, texte du PDF s'il existe |
| **Erreurs détectées** | Format non supporté, photo floue ou de travers, fichier vide, plusieurs pièces sur le même plan |

La quantité, le client et le délai ne figurent jamais sur un plan. Ils sont pourtant indispensables au prix : on les demande dès le dépôt.

### Étape 2 — Extraction

| | |
|---|---|
| **Entrées** | Images des pages, texte du PDF, contexte commercial |
| **Traitements** | Lecture du texte du PDF quand il existe (cotes, notes, nomenclature, exactes et sans OCR). L'IA comprend ensuite le dessin et produit un JSON au format imposé. |
| **Sorties** | Pour chaque champ : valeur, **niveau de confiance**, **zone du plan** d'où il vient |
| **Erreurs détectées** | Champs obligatoires manquants, réponse hors format, incohérence entre texte du PDF et lecture de l'IA |

Ce que l'IA extrait : identification (référence, désignation), matière, épaisseur, profil de pliage (ailes, angles, rayons), largeur, trous et découpes, chanfreins, nomenclature (composants), notes, traitement, tolérances.

Ce que l'IA **ne calcule pas** : surface développée, longueur de coupe, masse, prix.

### Étape 3 — Géométrie et faisabilité

**3a. Géométrie.** À partir des données extraites, le code construit :
- **la pièce à plat** (polygone 2D avec trous), calculée avec la formule du développé ;
- **le modèle 3D**, en extrudant le profil de pliage sur la largeur puis en retirant trous et chanfreins.

Les **mesures** utilisées par le chiffrage viennent de la pièce à plat, pas de l'IA :

| Mesure | Calcul |
|---|---|
| Rectangle englobant du flan | boîte englobante du polygone à plat |
| Surface nette | aire du polygone moins les trous |
| Longueur de coupe | périmètre extérieur + périmètres des trous |
| Nombre d'amorçages | 1 + nombre de contours intérieurs |
| Masse | surface nette × épaisseur × densité |

Si la pièce ne peut pas être construite (cotes contradictoires, aile de longueur négative), c'est déjà une erreur détectée.

Limite V1 : pièces dont **tous les plis sont parallèles** (supports, pattes, profils en L, U, Z). Les pièces avec des plis dans plusieurs directions sont prévues en V2.

**3b. Faisabilité.** Le moteur de règles évalue les règles définies par les experts métier :

| Exemple de règle | Paramètre type |
|---|---|
| Diamètre de trou ≥ épaisseur | 1,0 × e |
| Distance trou / bord ≥ k × épaisseur | 1,5 × e |
| Distance trou / pli ≥ 2 × épaisseur + rayon | 2 × e + R |
| Longueur d'aile ≥ minimum de l'outillage | 4 × e |
| Rayon de pliage ≥ épaisseur | 1,0 × e (plus pour certains aluminiums) |
| Dimensions du flan ≤ format de tôle et longueur de plieuse | selon `postes` |
| Épaisseur disponible pour la matière | selon `epaisseurs_dispo` |
| Traitement compatible avec la matière | galva → acier, anodisation → alu, passivation → inox |
| Épaisseur minimale pour un écrou à sertir | selon le composant |

Chaque règle produit une **alerte** (à vérifier) ou un **blocage** (devis impossible en l'état).

### Étape 4 — Validation humaine

L'écran présente côte à côte :
- le **plan d'origine**, avec surlignage de la zone d'un champ quand on clique dessus ;
- le **formulaire** pré-rempli, avec les champs manquants ou peu sûrs en premier ;
- le **modèle 3D** et des vues dessus / côté au même cadrage que le plan, pour comparer d'un coup d'œil ;
- les **alertes** de faisabilité ;
- le **prix provisoire**.

Les deux modes de correction sont détaillés en [section 4](#4-boucle-de-validation).

### Étape 5 — Chiffrage

| | |
|---|---|
| **Entrées** | Pièce validée, mesures géométriques, quantités, client |
| **Traitements** | Application des formules des 6 blocs ([logique_metier.md](logique_metier.md)) avec les tables de référence ([sources_donnees.md](sources_donnees.md)) |
| **Sorties** | Coût et prix par palier de quantité, **trace de chaque ligne** (formule, valeurs, table d'origine, date du prix) |
| **Erreurs détectées** | Bornes de `bornes_controle`, écart avec des devis similaires de l'historique, prix matière trop ancien |

À la validation, les valeurs utilisées sont **figées** dans le devis : le devis ne change plus si un prix de référence évolue ensuite.

### Étape 6 — Restitution et émission

| Vue interne | Vue client |
|---|---|
| Détail par bloc de coût | Désignation, référence |
| Temps, taux, réglages | Prix unitaire et total par palier de quantité |
| Marge appliquée (modifiable) | Options (ex. peinture) |
| Alertes et comparaison avec l'historique | Délai, validité, conditions |
| Trace complète du calcul | — |

Les modifications (marge, options, quantités) sont enregistrées avec leur auteur. L'émission génère le PDF client et ajoute le devis à l'historique.

---

## 4. Boucle de validation

```mermaid
flowchart LR
    M["Saisie directe<br/>(champs, menus déroulants)"] --> F
    T["Texte libre<br/>« c'est de l'inox 2 mm<br/>avec 4 écrous »"] --> L["IA : propose<br/>une modification"]
    L --> D["Affichage avant / après"]
    D -- "accepte" --> F["Formulaire<br/>(référence unique)"]
    D -- "refuse" --> X["Aucun changement"]
    F --> R["Recalcul<br/>géométrie, règles, prix"]
    R --> V["Mise à jour de l'écran"]
    V --> M
    V --> T
```

- Les menus déroulants sont alimentés par les tables de référence (matières, épaisseurs disponibles, traitements, composants) : on ne peut pas saisir une matière inconnue.
- Le texte libre **ne modifie jamais directement** les données. L'IA traduit la demande en modification du formulaire, que l'utilisateur accepte ou refuse.
- Chaque correction est enregistrée (valeur avant, valeur après, auteur, mode de saisie). Ces corrections servent à mesurer la qualité de l'extraction (voir [section 11](#11-traçabilité-et-confidentialité)).

---

## 5. Services techniques

```mermaid
flowchart LR
    UI["Interface web<br/>(tablette / PC)"] --> API["API<br/>orchestrateur"]

    API --> ING["Ingestion<br/>fichiers, photos,<br/>texte PDF"]
    API --> EXT["Extraction<br/>adaptateur IA"]
    API --> GEO["Géométrie<br/>3D, mise à plat,<br/>mesures"]
    API --> REG["Moteur<br/>de règles"]
    API --> CHF["Moteur<br/>de chiffrage"]
    API --> DOC["Génération<br/>de documents"]
    API --> ADM["Administration<br/>référentiels"]

    EXT --> LLM["Fournisseur IA<br/>externe ou interne"]

    ING --> FS[("Stockage<br/>fichiers")]
    GEO --> FS
    DOC --> FS

    REG --> DB[("Base de<br/>données")]
    CHF --> DB
    ADM --> DB
    API --> DB

    PURGE["Tâche planifiée<br/>conservation / purge"] --> FS
    PURGE --> DB
```

| Service | Rôle | Déterministe ? |
|---|---|---|
| **Interface web** | Écrans du parcours et de l'administration, utilisable sur tablette | — |
| **API / orchestrateur** | Enchaîne les étapes, gère le statut du devis, enregistre la trace | Oui |
| **Ingestion** | Réception des fichiers, conversion en images, lecture du texte PDF, redressement des photos | Oui |
| **Extraction** | Envoi au fournisseur IA, contrôle du format de réponse, fusion avec le texte du PDF | **Non (IA)** |
| **Géométrie** | Construction de la pièce à plat et du modèle 3D, calcul des mesures | Oui |
| **Moteur de règles** | Évaluation des règles de faisabilité et des bornes de contrôle | Oui |
| **Moteur de chiffrage** | Calcul des 6 blocs, marge, paliers, trace | Oui |
| **Génération de documents** | PDF client, export de la vue interne | Oui |
| **Administration** | Gestion des tables de référence, des règles et des clients | Oui |
| **Conservation / purge** | Suppression des plans et modèles selon les règles de chaque client | Oui |

Seul le service d'extraction (et l'assistant de correction) fait appel à l'IA. Tout le reste est reproductible : même entrée, même résultat.

En V1, ces services peuvent être des **modules d'une même application** plutôt que des services séparés. Le découpage reste le même, ce qui permet de les séparer plus tard si besoin.

---

## 6. Flux de données

```mermaid
sequenceDiagram
    actor U as Chargé d'affaires
    participant UI as Interface
    participant API as Orchestrateur
    participant EXT as Extraction
    participant LLM as Fournisseur IA
    participant GEO as Géométrie
    participant REG as Règles
    participant CHF as Chiffrage
    participant DOC as Documents

    U->>UI: Dépose le plan + contexte commercial
    UI->>API: Création du devis
    API->>EXT: Images + texte du PDF
    EXT->>LLM: Image + instructions + format JSON imposé
    LLM-->>EXT: JSON brut
    EXT-->>API: Champs + confiance + zones du plan

    API->>GEO: Données de la pièce
    GEO-->>API: Pièce à plat, modèle 3D, mesures
    API->>REG: Pièce + mesures
    REG-->>API: Alertes / blocages
    API->>CHF: Pièce + mesures + quantités
    CHF-->>API: Prix provisoire + trace
    API-->>UI: Formulaire pré-rempli, 3D, alertes, prix provisoire

    loop Corrections
        U->>UI: Modifie un champ ou écrit en texte libre
        UI->>API: Modification acceptée
        API->>GEO: Recalcul
        API->>REG: Recalcul
        API->>CHF: Recalcul
        API-->>UI: Écran mis à jour
    end

    U->>UI: Valide la pièce
    API->>CHF: Calcul final, prix figés
    U->>UI: Ajuste marge / options, puis émet
    API->>DOC: Génération du PDF client
    DOC-->>UI: Devis PDF téléchargeable
```

---

## 7. Cycle de vie d'un devis

```mermaid
stateDiagram-v2
    [*] --> Brouillon : dépôt du plan
    Brouillon --> EnValidation : extraction terminée
    EnValidation --> EnValidation : correction
    EnValidation --> Bloque : règle bloquante
    Bloque --> EnValidation : correction
    EnValidation --> Valide : validation humaine
    Valide --> EnValidation : réouverture
    Valide --> Emis : PDF généré
    Emis --> Accepte : commande
    Emis --> Refuse : refus client
    Emis --> Expire : fin de validité
    Accepte --> [*]
    Refuse --> Purge : suppression du plan
    Expire --> Purge : suppression du plan
    Purge --> [*]
```

La suppression du plan après un refus ou une expiration dépend des réglages du client (voir [section 11](#11-traçabilité-et-confidentialité)). Les caractéristiques résumées et le devis émis restent dans l'historique.

---

## 8. Modèle de données

Les tables de référence (matières, postes, temps, composants, traitements, paramètres, clients, bornes) sont décrites dans [sources_donnees.md](sources_donnees.md). Ce schéma montre les objets propres à un devis.

```mermaid
erDiagram
    CLIENTS ||--o{ DEVIS : "demande"
    DEVIS ||--o| FICHIER_PLAN : "plan d'origine"
    DEVIS ||--o{ EXTRACTION : "versions"
    DEVIS ||--o{ CORRECTION : "modifications"
    DEVIS ||--o| PIECE_VALIDEE : "aboutit à"
    PIECE_VALIDEE ||--o| GEOMETRIE : "produit"
    DEVIS ||--o{ ALERTE : "contient"
    DEVIS ||--o{ LIGNE_CALCUL : "détail du prix"
    DEVIS ||--o| INSTANTANE_PRIX : "prix figés"
    DEVIS ||--o| RESUME_PIECE : "alimente l'historique"
```

| Objet | Contenu | Sensibilité |
|---|---|---|
| `DEVIS` | Numéro, client, statut, quantités, marge, auteur, dates | Moyenne |
| `FICHIER_PLAN` | Fichier d'origine, images des pages, texte PDF | **Très forte** (propriété du client) |
| `EXTRACTION` | JSON brut renvoyé par l'IA, fournisseur, version du prompt, durée | Forte |
| `CORRECTION` | Champ, valeur avant / après, auteur, mode (formulaire ou texte libre) | Forte |
| `PIECE_VALIDEE` | Données de la pièce après validation humaine | Forte |
| `GEOMETRIE` | Pièce à plat (DXF), modèle 3D, mesures | **Très forte** (permet de reconstruire la pièce) |
| `ALERTE` | Règle, niveau, message, statut (vue / ignorée avec justification) | Faible |
| `LIGNE_CALCUL` | Bloc, formule, valeurs, table d'origine, date du prix | Moyenne |
| `INSTANTANE_PRIX` | Copie des valeurs de référence utilisées | Faible |
| `RESUME_PIECE` | Matière, épaisseur, dimensions hors-tout, nb plis / trous / composants, prix | Faible (ne permet pas de reconstruire la pièce) |

---

## 9. Intégration de l'IA

### 9.1 Où intervient l'IA

| Moment | Rôle de l'IA | Garde-fou |
|---|---|---|
| Étape 2 — Extraction | Comprendre le plan et produire un JSON structuré | Format imposé, confiance par champ, contrôles de cohérence, validation humaine |
| Étape 4 — Assistant | Traduire une correction en texte libre en modification du formulaire | Affichage avant / après, acceptation explicite |
| Étape 6 — Comparaison (option) | Retrouver des devis similaires dans l'historique | Seulement les caractéristiques résumées, jamais le plan d'un autre client |

L'IA n'intervient **ni dans la géométrie, ni dans les règles, ni dans le prix**.

### 9.2 Adaptateur de fournisseur

Le service d'extraction passe par une **interface commune** qui permet de changer de fournisseur sans toucher au reste :
- fournisseurs externes via API (Anthropic, OpenAI, Mistral, Azure OpenAI…) ;
- modèle hébergé en interne, pour les clients qui interdisent l'envoi de leurs plans à un tiers.

Le choix du fournisseur se fait selon le réglage du client (`ia_externe_autorisee`). Un abonnement grand public ne suffit pas : il faut un **contrat API ou entreprise** avec garantie de non-réutilisation des données.

**Pour le prototype : [OpenRouter](https://openrouter.ai/).** Une seule clé et une API au format OpenAI donnent accès à de nombreux modèles capables de lire des images (Claude, GPT, Gemini, Qwen-VL…). Avantages :
- l'adaptateur n'a qu'une seule implémentation pour la V1 ;
- on peut **comparer plusieurs modèles** sur le jeu d'évaluation en changeant un seul paramètre (voir [section 15](#15-évaluation-de-lextraction)).

En production, OpenRouter ajoute un intermédiaire entre l'usine et le fournisseur du modèle. Ses réglages de confidentialité (exclusion des fournisseurs qui conservent les données) devront être vérifiés, ou on passera par un contrat direct avec le fournisseur retenu.

### 9.3 Format de sortie

Chaque champ extrait suit la même structure :

```json
{
  "epaisseur_mm": {
    "valeur": 2,
    "confiance": 0.95,
    "source": { "page": 1, "zone": [212, 455, 40, 60] }
  },
  "matiere": {
    "valeur": null,
    "confiance": 0.0,
    "source": null
  },
  "plis": {
    "valeur": [
      { "angle_deg": 90, "rayon_int_mm": 2 },
      { "angle_deg": 90, "rayon_int_mm": 2 }
    ],
    "confiance": 0.8,
    "source": { "page": 1, "zone": [212, 455, 200, 140] }
  }
}
```

Le prompt et le schéma JSON complets seront détaillés dans un document dédié.

---

## 10. Gestion des erreurs

Les erreurs sont détectées à **trois niveaux**, chacun avec sa réponse :

```mermaid
flowchart TD
    N1["Niveau 1 — Extraction<br/>Le plan a-t-il été bien lu ?"]
    N2["Niveau 2 — Faisabilité<br/>La pièce est-elle cohérente et fabricable ?"]
    N3["Niveau 3 — Prix<br/>Le prix est-il plausible ?"]
    N1 --> N2 --> N3

    N1 --- C1["Champs obligatoires manquants<br/>Confiance faible<br/>Texte PDF ≠ lecture IA"]
    N2 --- C2["Pièce impossible à construire<br/>Règles experts non respectées<br/>Épaisseur ou traitement indisponible"]
    N3 --- C3["Prix hors bornes (€/kg, part matière)<br/>Écart avec l'historique<br/>Prix de référence trop ancien"]
```

| Niveau | Détection | Correction |
|---|---|---|
| **1. Extraction** | Champ vide ou confiance faible, réponse hors format, désaccord entre le texte du PDF et l'IA | Champ mis en avant dans le formulaire, l'utilisateur complète ou corrige |
| **2. Faisabilité** | Modèle 3D impossible à construire, règle non respectée, dimensions hors capacité | Alerte ou blocage avec message clair. L'utilisateur corrige, ou justifie s'il ignore une alerte |
| **3. Prix** | Bornes de `bornes_controle`, écart > 30 % avec des pièces similaires, prix matière ancien | Alerte dans la vue interne, avec le détail du calcul pour trouver la ligne en cause |

### Scénario de démonstration

En reprenant les erreurs de la fiche [devis.pdf](../exercise_information/devis.pdf) fournie :

| Erreur | Niveau | Ce que voit l'utilisateur |
|---|---|---|
| Matière « non renseignée » | 1 | Champ obligatoire en rouge, prix non calculable tant qu'il est vide |
| Plis à 45° au lieu de 90° | 2 | Le modèle 3D ne correspond visiblement pas au plan, et la hauteur de 22 mm ne peut pas être atteinte |
| Surface développée de 0,0004 m² | — | Impossible dans notre architecture : la surface est calculée par le code à partir de la pièce à plat |
| Longueur de découpe de 40 mm | — | Idem : calculée par le code (≈ 343 mm) |
| Prix aberrant volontairement introduit | 3 | Alerte « écart de +180 % avec 3 pièces similaires », avec le détail du calcul |

---

## 11. Traçabilité et confidentialité

> Les points ci-dessous structurent l'architecture. Ils sont à valider avec le service juridique ou le DPO du groupe.

### 11.1 Le cadre

- **Les plans sont la propriété intellectuelle du client**, protégés par le secret des affaires et généralement par un accord de confidentialité ou les conditions générales d'achat du client. Ces clauses limitent souvent l'usage du plan à la réponse à la demande de prix, et imposent sa destruction sur demande ou si la commande n'aboutit pas.
- **Usage prévu** : le plan est transmis pour obtenir un devis. L'utiliser pour améliorer un modèle est un autre usage, qui demande une base contractuelle ou l'accord explicite du client.
- **Envoi à un fournisseur d'IA** : c'est un transfert à un tiers. Il faut un contrat de sous-traitance, une garantie de non-réutilisation des données et idéalement un hébergement en Europe. Certains clients l'interdisent.
- **RGPD** : le cartouche peut contenir des noms ou contacts (données personnelles), à limiter au strict nécessaire.
- **AI Act** : un outil d'aide au devis n'entre pas dans les systèmes à haut risque. Les obligations sont limitées (transparence, supervision humaine, déjà prévue).

### 11.2 Séparer les données selon leur sensibilité

| Donnée | Propriétaire | Conservation proposée |
|---|---|---|
| Plan d'origine | Client | Pendant la consultation. Suppression si offre refusée, expirée ou sur demande, sinon selon le contrat |
| Géométrie complète (3D, mise à plat) | Client | Même règle que le plan |
| Extraction brute et corrections | Mixte | Même règle que le plan, sauf accord du client pour l'évaluation |
| Résumé de la pièce (matière, épaisseur, dimensions hors-tout, nb plis / trous, prix) | Maji | Conservé, pour l'historique et la comparaison des prix |
| Devis émis | Maji | Conservé (obligatoire s'il devient une commande) |

Ce qui sert à comparer les prix **ne permet pas de reconstruire la pièce** : l'historique survit à la suppression du plan.

### 11.3 Réglages par client

Ajouts à la table `clients` ([sources_donnees.md §3.1](sources_donnees.md#31-clients)) :

| Colonne | Défaut | Effet |
|---|---|---|
| `ia_externe_autorisee` | non | Si non : modèle interne ou saisie manuelle assistée |
| `reutilisation_autorisee` | non | Si oui : le plan et ses corrections peuvent rejoindre le jeu d'évaluation |
| `duree_conservation_plans_jours` | 90 | Délai avant suppression automatique |
| `suppression_si_refus` | oui | Suppression du plan dès le refus de l'offre |

Par défaut, on applique la règle **la plus protectrice**.

### 11.4 Suppression et preuve

Une tâche planifiée supprime les plans, géométries, extractions et corrections selon ces réglages. Chaque suppression est enregistrée (quoi, quand, pourquoi) pour pouvoir le prouver au client.

### 11.5 Améliorer l'outil sans entraîner de modèle

L'architecture **n'a pas besoin d'entraîner de modèle**. On améliore l'extraction en ajustant les instructions données à l'IA, et on mesure la qualité sur un **jeu d'évaluation** :
- composé uniquement de plans autorisés : clients ayant donné leur accord, plans internes à Maji, plans créés pour l'occasion ;
- avec les bonnes réponses connues pour chaque champ ;
- qui produit un taux de bonnes réponses par champ, suivi à chaque changement de prompt ou de fournisseur.

Les corrections faites par les utilisateurs (sur les plans autorisés) enrichissent ce jeu d'évaluation au fil du temps.

---

## 12. Administration

Espace séparé du parcours, utilisé par d'autres profils :

| Écran | Utilisateur | Tables |
|---|---|---|
| Matières et épaisseurs | Acheteur | `matieres`, `epaisseurs_dispo` |
| Composants et traitements | Acheteur | `composants`, `traitements` |
| Postes et taux horaires | Contrôleur de gestion | `postes` |
| Temps standards | Bureau des méthodes | `vitesses_coupe`, `temps_pliage`, `operations` |
| Règles de faisabilité et bornes | Bureau des méthodes | `regles_faisabilite`, `bornes_controle` |
| Clients et conservation | Direction commerciale | `clients`, `parametres` |
| Qualité de l'extraction | Data scientist | Jeu d'évaluation, résultats |

Chaque modification est datée et attribuée. Les devis déjà émis ne sont pas affectés, grâce aux prix figés.

---

## 13. Stack technique proposée

> **Décidé** : Python, Streamlit, OpenRouter, modèle 3D dès la V1 (abandonné s'il s'avère trop coûteux à mettre au point). Le reste est une proposition.

| Brique | Proposition | Pourquoi |
|---|---|---|
| Langage backend | **Python** | Écosystème data, CAO (CadQuery) et IA |
| API | **FastAPI** | Simple, typée, documentation automatique |
| Schémas de données | **Pydantic** | Même définition pour le format JSON de l'IA, l'API et la validation |
| Lecture PDF | **PyMuPDF** | Texte du PDF + rendu en image |
| Photos | **OpenCV** | Redressement, contraste, détection de flou |
| IA | **OpenRouter** (API au format OpenAI) derrière une interface commune | Accès à plusieurs modèles, comparaison facile, changement de fournisseur sans impact |
| Pièce à plat et mesures | **Shapely** + **ezdxf** | Polygone 2D, aire, périmètre, export DXF |
| Modèle 3D | **CadQuery** ou **build123d**, export GLB / STL | Construction paramétrique en Python |
| Affichage 3D | **Plotly** (maillage 3D, intégré nativement à Streamlit) | Rotation / zoom sans développement front |
| Moteur de règles | Types de règles prédéfinis avec paramètres en base | Modifiable par les experts sans exécuter de code arbitraire |
| Base de données | **SQLite** (V1) → **PostgreSQL** | Simple pour le prototype, migration directe |
| Stockage fichiers | Dossier local (V1) → stockage objet (S3 / MinIO) | |
| PDF devis | **WeasyPrint** (HTML → PDF) | Mise en page en HTML/CSS |
| Interface | **Streamlit** | Tout en Python, rapide à développer et facile à relire. React reste une option pour une version de production plus adaptée à la tablette |

---

## 14. Périmètre V1 / V2

| Fonction | V1 (prototype) | V2 |
|---|---|---|
| Formats acceptés | PDF, image, photo | + STEP, DXF (géométrie exacte, sans IA) |
| Pièces | Une pièce par plan, plis parallèles | Plis dans plusieurs directions, assemblages, plans multi-pages |
| Extraction | Un fournisseur IA externe | Plusieurs fournisseurs + modèle interne |
| Correction | Formulaire + assistant texte libre | — |
| Géométrie | Pièce à plat + 3D simple | Détection des collisions au pliage |
| Faisabilité | ~10 règles | Règles complètes du bureau des méthodes |
| Chiffrage | 6 blocs, données simulées | Données réelles de chaque usine, calepinage réel |
| Historique | Faux devis simulés | Import des devis Excel existants |
| Confidentialité | Réglages par client + purge | Audit complet |
| Utilisateurs | Hors périmètre (utilisateur unique) | Authentification, rôles (chargé d'affaires, admin, direction) |
| Évaluation | Jeu synthétique généré + quelques plans réels annotés | Plans réels autorisés, suivi continu de la qualité |

---

## 15. Évaluation de l'extraction

L'extraction est la seule étape non déterministe : c'est elle qu'il faut mesurer. Le protocole complet est décrit dans **[evaluation.md](evaluation.md)**.

En résumé :
- **trois jeux de données** : des plans de tôlerie générés avec leurs bonnes réponses (référence principale), quelques vrais plans annotés à la main (contrôle de réalisme), et CADExpert (repli et complément) ;
- **plusieurs niveaux de dégradation** : PDF propre, image, scan, photo, plans volontairement erronés ;
- **des indicateurs orientés métier** : exactitude par champ, taux d'invention, fiabilité de la confiance annoncée, et surtout **écart sur le prix final** ;
- **4 à 6 modèles** comparés via OpenRouter, avec une séparation stricte entre jeu de développement et jeu de test.

---

## 16. Décisions et points ouverts

**Décidé**

- [x] Langage : Python
- [x] Interface : Streamlit
- [x] Fournisseur IA pour le prototype : OpenRouter
- [x] Modèle 3D dès la V1 (abandonné s'il s'avère trop coûteux à mettre au point)
- [x] Évaluation : plans générés + vrais plans annotés + CADExpert en repli ([evaluation.md](evaluation.md))
- [x] Gestion des utilisateurs et des rôles : hors périmètre

**Ouvert**

- [ ] Modèles à comparer via OpenRouter (liste exacte au moment de l'exécution)
- [ ] Contenu réel des plans des projets open source candidats (jeu B)
- [ ] Plans réels anonymisés fournis par l'entreprise (à demander)
