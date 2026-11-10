# `data` — base de référence des coûts

Base SQLite unique regroupant les 12 référentiels du chiffrage (matières, postes, opérations, paramètres, clients, historique…). SQLAlchemy 2.0 pour le schéma (`tables.py`), Alembic pour les migrations (`alembic/` à la racine).

**Le détail métier de chaque table** (rôle, colonnes, valeurs simulées, sources réelles) est dans [docs/sources_donnees.md](../../../docs/sources_donnees.md) — c'est la source de vérité, ne pas le dupliquer ici.

## Mise en route

```bash
uv run alembic upgrade head   # crée / met à jour data/devis.db (gitignorée)
```

## Conventions

- **Aucune valeur en dur** : tout chiffre utilisé dans un calcul vient de ces tables. Les valeurs simulées vivront dans un seul module de seed (à venir), pas dans le code du moteur.
- **Pydantic en lecture typée** : la base stocke, Pydantic valide et type à la lecture.
- **`parametres.valeur` est en texte** : elle accueille des nombres (`"0.25"`), des listes (`"1,10,100,1000"`) ou du texte (`"EUR"`) ; le cast dépend de la clé et se fait à la lecture.
- **Migrations** : écrites à la main et relues (l'autogenerate ne détecte pas les changements de clé primaire, et SQLite impose de recréer la table : `CREATE TABLE …_nouvelle`, `INSERT … SELECT`, `DROP`, `RENAME`). Vérifier `upgrade` **et** `downgrade` avant de committer.

## Schéma des tables

```mermaid
erDiagram
    matieres {
        string id PK
        string famille
        string nuance
        string norme
        float densite_kg_dm3
        float prix_eur_kg
        date date_maj
        string fournisseur
    }
    epaisseurs_dispo {
        string matiere_id PK,FK
        float epaisseur_mm PK
        string format_mm
        float surcout_pct
        bool en_stock
    }
    postes {
        string id PK
        string nom
        string type
        float taux_horaire_eur_h
        float temps_reglage_min
    }
    vitesses_coupe {
        string poste_id PK,FK
        string famille PK
        float epaisseur_mm PK
        float vitesse_m_min
        float temps_amorcage_s
        string gaz
    }
    temps_pliage {
        string categorie PK
        int dim_max_mm PK
        float epaisseur_max_mm PK
        float temps_par_pli_s
        float temps_retournement_s
        int nb_operateurs
    }
    operations {
        string id PK
        string nom
        string poste_id FK
        float temps_s
        string unite
    }
    composants {
        string reference PK
        string designation
        string type
        string filetage
        string matiere
        float prix_unitaire_eur
        int qte_min
        string operation_id FK
    }
    traitements {
        string id PK
        string nom
        float prix
        string unite
        float minimum_lot_eur
        int delai_jours
        string matieres_compatibles
    }
    parametres {
        string cle PK
        string valeur
        string unite
        string description
    }
    clients {
        string id PK
        string nom
        string secteur
        float marge_specifique
        bool ia_externe_autorisee
        bool reutilisation_autorisee
        int duree_conservation_plans_jours
        bool suppression_si_refus
    }
    historique_devis {
        string id PK
        date date
        string client_id FK
        string reference_piece
        string designation
        string matiere_id FK
        float epaisseur_mm
        float flan_l_mm
        float flan_w_mm
        float masse_kg
        float longueur_coupe_mm
        int nb_trous
        int nb_plis
        int nb_composants
        string traitement_id FK
        int quantite
        float cout_unitaire_eur
        float prix_unitaire_eur
        string statut
    }
    bornes_controle {
        string champ PK
        float min
        float max
        string niveau
        string message
    }

    matieres ||--o{ epaisseurs_dispo : "disponible en"
    matieres ||..o{ vitesses_coupe : "famille (clé logique)"
    postes ||--o{ vitesses_coupe : "machine"
    postes |o--o{ operations : "réalisée sur"
    operations |o--o{ composants : "posée par"
    clients |o--o{ historique_devis : "a demandé"
    matieres |o--o{ historique_devis : "en"
    traitements |o--o{ historique_devis : "avec"
```

`parametres`, `temps_pliage` et `bornes_controle` sont des tables autonomes, sans clé étrangère. Le lien entre `vitesses_coupe` et `matieres` est logique (via la colonne `famille`, pas une clé étrangère) : il est en pointillés.
