# Générateur de devis — Tôlerie / Usinage

Prototype d'un outil interne qui génère automatiquement un devis à partir d'un plan technique de pièce de tôlerie ou d'usinage.

Projet réalisé dans le cadre du cas pratique « Data Scientist » du groupe Maji (voir [exercise_information/](exercise_information/)).

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
| [docs/architecture.md](docs/architecture.md) | Architecture : parcours utilisateur, services, flux de données, gestion des erreurs, traçabilité et confidentialité, stack proposée |

## Structure du dépôt

```
.
├── README.md
├── docs/
│   ├── logique_metier.md        # Guide de la logique de chiffrage
│   ├── sources_donnees.md       # Référentiels de données du chiffrage
│   └── architecture.md          # Architecture fonctionnelle et technique
└── exercise_information/        # Énoncé et documents fournis
    ├── Cas Pratique Responsable Data Scientist.pdf
    ├── piece_003.pdf            # Exemple de plan
    └── devis.pdf                # Exemple de fiche de devis attendue
```

## Avancement

- [x] Étude de la logique métier du chiffrage tôlerie ([docs/logique_metier.md](docs/logique_metier.md))
- [x] Définition des référentiels de données ([docs/sources_donnees.md](docs/sources_donnees.md))
- [ ] Création des données simulées
- [x] Architecture fonctionnelle et technique ([docs/architecture.md](docs/architecture.md))
- [x] Choix de la stack : Python, Streamlit, OpenRouter
- [ ] Extraction des caractéristiques depuis un plan
- [ ] Jeu d'évaluation synthétique (génération de plans + dégradations)
- [ ] Moteur de calcul des coûts
- [ ] Génération du devis
- [ ] Interface utilisateur
- [ ] Contrôles de fiabilité
