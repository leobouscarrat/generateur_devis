# Générateur de devis — Tôlerie / Usinage

Prototype d'un outil interne qui génère automatiquement un devis à partir d'un plan technique de pièce de tôlerie ou d'usinage.

Projet réalisé dans le cadre du cas pratique « Data Scientist » du groupe Maji.

## Contexte

Aujourd'hui, les devis sont faits à la main sur Excel. Ce processus est :

- **long** : il faut relire le plan, mesurer, ressaisir ;
- **peu fiable** : erreurs de saisie et formules différentes d'une personne à l'autre ;
- **dépendant de multiples sources** : prix matière, composants, temps machine.

L'objectif est de rendre ce processus plus rapide, plus fiable et plus homogène.

## Principe

```
Dépôt + contexte → Extraction (IA) → Géométrie & faisabilité → Validation humaine → Chiffrage → Devis
                                              ▲                        │
                                              └──── corrections ───────┘
```

1. **Dépôt** du plan (PDF, image, photo) et saisie du contexte commercial (client, quantités, délai).
2. **Extraction** par l'IA des caractéristiques utiles : matière, épaisseur, profil de pliage, trous, composants, traitement, tolérances.
3. **Géométrie et faisabilité** : le code reconstruit la pièce à plat et en 3D, en calcule les mesures (surface, longueur de coupe, masse) et vérifie les règles de fabrication définies par les experts.
4. **Validation** par l'utilisateur, via un formulaire ou un assistant en texte libre. Chaque correction relance l'étape 3 et le prix.
5. **Chiffrage** par un moteur déterministe, qui décompose la fabrication en **6 blocs de coût** :
   1. Matière
   2. Découpe
   3. Pliage
   4. Soudure / assemblage
   5. Finition / traitement de surface
   6. Composants achetés & opérations secondaires
6. **Restitution** : vue interne (coûts, marge, alertes) et vue client, puis génération du devis PDF.

Toute l'architecture est détaillée dans [docs/architecture.md](docs/architecture.md).

L'IA sert à **lire et comprendre le plan**. Elle ne calcule **ni la géométrie ni le prix** : ils viennent toujours de formules transparentes et de paramètres modifiables.

## Documentation

| Document | Contenu |
|---|---|
| [docs/logique_metier.md](docs/logique_metier.md) | Méthode de chiffrage : les 6 blocs de coût, formules, hypothèses, paramètres par défaut, contrôles de cohérence, exemple complet sur `piece_003` |
| [docs/sources_donnees.md](docs/sources_donnees.md) | Référentiels de données nécessaires au calcul (matières, postes, temps, composants, traitements…) : structure, valeurs simulées, équivalent dans une vraie usine |
| [docs/evaluation.md](docs/evaluation.md) | Protocole d'évaluation de l'extraction : jeux de données, dégradations, indicateurs, modèles, budget |
| [docs/architecture.md](docs/architecture.md) | Architecture : parcours utilisateur, services, flux de données, gestion des erreurs, traçabilité et confidentialité, stack proposée |

## Structure du dépôt

```
.
├── README.md
├── docs/
│   ├── logique_metier.md        # Guide de la logique de chiffrage
│   ├── sources_donnees.md       # Référentiels de données du chiffrage
│   ├── architecture.md          # Architecture fonctionnelle et technique
│   └── evaluation.md            # Protocole d'évaluation de l'extraction
└── exercise_information/        # Énoncé et documents fournis (local uniquement, non versionné)
```

## Avancement

Le projet est découpé en deux parties.

**Partie 1 — Évaluation de la qualité de l'extraction** (en cours, voir [docs/evaluation.md](docs/evaluation.md))

- [x] Protocole d'évaluation
- [ ] Format de sortie (schéma JSON de la pièce)
- [ ] Générateur de pièces de tôlerie et mise en plan
- [ ] Dégradations (image, scan, photo, plans erronés)
- [ ] Jeu de vrais plans annotés
- [ ] Chargement de CADExpert
- [ ] Exécution sur les modèles et rapport de résultats

**Partie 2 — Outil de devis**

- [x] Logique métier du chiffrage ([docs/logique_metier.md](docs/logique_metier.md))
- [x] Référentiels de données ([docs/sources_donnees.md](docs/sources_donnees.md))
- [x] Architecture ([docs/architecture.md](docs/architecture.md)) et stack : Python, Streamlit, OpenRouter
- [ ] Création des données simulées
- [ ] Extraction, géométrie et faisabilité
- [ ] Moteur de calcul des coûts
- [ ] Interface et génération du devis
