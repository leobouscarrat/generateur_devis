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
| [docs/resultats.md](docs/resultats.md) | Résultats de l'évaluation et comparaison de 3 modèles (Claude Sonnet, Gemini Flash, Qwen open source) |
| [docs/jeux_de_test.md](docs/jeux_de_test.md) | Composition des jeux de test et exemples en image : niveaux de qualité (PDF, scan, photo), plans erronés et incohérents |
| [docs/architecture.md](docs/architecture.md) | Architecture : parcours utilisateur, services, flux de données, gestion des erreurs, traçabilité et confidentialité, stack proposée |

## Démarrage

Prérequis : [uv](https://docs.astral.sh/uv/) et Python 3.12 ou plus.

```bash
uv sync                                          # installe l'application et l'étude
uv sync --no-group etude                         # application seule (sans les dépendances de l'étude)
cp .env.example .env                             # puis renseigner les clés d'API
uv run pytest                                    # lance les tests
uv run python -m generateur_devis.schema.export  # régénère le JSON Schema de la pièce
```

Extraire un plan avec un modèle :

```bash
# Abonnement Claude, via Claude Code (aucune clé à fournir si l'extension VS Code est connectée)
uv run python -m generateur_devis.extraction PLAN.pdf --modele claude-code:sonnet
# OpenRouter (clé OPENROUTER_API_KEY dans .env)
uv run python -m generateur_devis.extraction PLAN.pdf --modele openrouter:<modèle> --sortie fiche.json
```

Pendant l'étude, les réponses sont mises en cache dans `results/cache/` : un même plan n'est jamais redemandé au même modèle. L'application, elle, ne garde aucune réponse sur disque : les extractions réussies sont gardées en mémoire du serveur jusqu'à son redémarrage, et un plan redéposé (après un rechargement de page, par exemple) est repris sans nouvel appel IA.

Évaluer un modèle sur un jeu (cadsy, ecado, prive, tolerie, tolerie_erreurs ou tolerie_incoherences), partie développement ou test :

```bash
uv run python -m etude_extraction --jeu ecado --partie dev --modele claude-code:sonnet
uv run python -m etude_extraction --jeu tolerie --niveau 3 --partie test   # photos
uv run python -m etude_extraction --jeu tolerie_erreurs --partie test      # plans erronés
uv run python -m etude_extraction --jeu tolerie_incoherences --partie test # plans incohérents
```

Niveaux du jeu tôlerie : 0 PDF propre, 1 image propre, 2 scan, 3 photo.

Les jeux publics sont téléchargés automatiquement dans `data/raw/`. Les résultats détaillés sont écrits dans `results/runs/`.

### Administration des référentiels

```bash
uv run streamlit run src/generateur_devis/ui/admin.py
```

L'écran exige une connexion (démonstration — ce n'est **pas une sécurité réelle**, le code côté client reste lisible). Les comptes se déclarent dans `.streamlit/secrets.toml` (gitignoré) :

```toml
[admin.utilisateurs]
acheteur = "prix2026"
methodes = "temps2026"
direction = "pilotage2026"
```

Le nom de connexion devient l'auteur de chaque modification (audit daté et attribué, visible en bas de l'écran).

La section « Consulter les référentiels » affiche en lecture seule, sans appel IA, les valeurs en vigueur de chaque table administrable (clé et champs modifiables par l'agent), pour formuler une mise à jour en connaissant la valeur actuelle.

Limite assumée de cette connexion de démonstration : elle ne vit que dans la session Streamlit. Recharger la page (F5, retour arrière) déconnecte et perd la proposition de l'agent en attente — l'écran l'avertit tant qu'une proposition attend d'être acceptée ou refusée. Une session persistante est hors périmètre V1.

## Structure du dépôt

```
.
├── README.md
├── pyproject.toml
├── docs/
│   ├── logique_metier.md        # Guide de la logique de chiffrage
│   ├── sources_donnees.md       # Référentiels de données du chiffrage
│   ├── architecture.md          # Architecture fonctionnelle et technique
│   ├── evaluation.md            # Protocole d'évaluation de l'extraction
│   ├── resultats.md             # Résultats de l'évaluation
│   └── jeux_de_test.md          # Composition des jeux de test, exemples en image (docs/images/)
├── src/generateur_devis/         # APPLICATION
│   ├── schema/                  # Format JSON de la pièce (Pydantic), partagé par tout le projet
│   ├── llm/                     # Accès aux modèles : Claude Code, OpenRouter, Nous Research
│   └── extraction/              # Plan → images + texte, prompt, validation
├── src/etude_extraction/        # ÉTUDE de la qualité de l'extraction (n'est jamais importée par l'application)
│   ├── generateur/              # Générateur de plans de tôlerie avec leur bonne réponse
│   ├── degradations.py          # Scan et photo simulés
│   ├── jeux.py                  # Jeux (cadsy, ecado, privé, tôlerie, erronés, incohérents)
│   └── comparaison.py, executer.py  # Comparaison champ par champ, synthèse, cache des réponses
├── schemas/
│   └── piece_extraite.schema.json  # Export JSON Schema du format (généré)
├── exemples/
│   └── equerre_fictive.json     # Exemple de pièce au format
├── tests/
├── data/prive/                  # Annotations de plans non versionnés (local uniquement)
└── exercise_information/        # Énoncé et documents fournis (local uniquement)
```

## Avancement

Le projet est découpé en deux parties.

**Partie 1 — Évaluation de la qualité de l'extraction** (en cours, voir [docs/evaluation.md](docs/evaluation.md))

- [x] Protocole d'évaluation
- [x] Format de sortie : schéma JSON de la pièce ([src/generateur_devis/schema/piece.py](src/generateur_devis/schema/piece.py))
- [x] Générateur de plans de tôlerie et mise en plan (`uv run python -m etude_extraction.generateur`)
- [x] Accès aux modèles et extraction de bout en bout (premier essai sur piece_003)
- [x] Dégradations (scan, photo) et plans volontairement erronés
- [x] Chargement de cadsy et ecado, comparaison champ par champ, premiers résultats (développement)
- [x] Plans erronés et incohérents (signalement plutôt qu'invention)
- [ ] ~~Jeu de vrais plans annotés~~ : pas d'autre vrai plan disponible (piece_003 seul), reporté à la phase pilote
- [x] Résultats sur tous les jeux de test, avec Claude Sonnet ([docs/resultats.md](docs/resultats.md))
- [x] Comparaison avec d'autres modèles (Gemini 2.5 Flash, Qwen3.8 27B)

**Partie 2 — Outil de devis**

- [x] Logique métier du chiffrage ([docs/logique_metier.md](docs/logique_metier.md))
- [x] Référentiels de données ([docs/sources_donnees.md](docs/sources_donnees.md))
- [x] Architecture ([docs/architecture.md](docs/architecture.md)) et stack : Python, Streamlit, OpenRouter
- [x] Création des données simulées
- [x] Extraction, géométrie et faisabilité
- [x] Moteur de calcul des coûts
- [x] Interface et génération du devis
- [x] Administration des référentiels (docs/architecture.md §12 : matières/prix, postes/taux, temps standards, bornes, clients — chaque modification datée et attribuée)
