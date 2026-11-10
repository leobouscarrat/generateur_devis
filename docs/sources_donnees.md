# Sources de données — Référentiels du chiffrage

Ce document liste les données de référence dont le moteur de calcul a besoin pour chiffrer une pièce. Il complète le guide [logique_metier.md](logique_metier.md), qui décrit les formules.

Dans une usine, ces données existent déjà, mais elles sont dispersées : fichiers Excel, ERP, catalogues fournisseurs, connaissance des chefs d'atelier. L'outil les regroupe dans une base unique. Comme nous n'avons pas de données réelles, **toutes les valeurs ci-dessous sont simulées**, à partir des ordres de grandeur sourcés dans le guide.

---

## Sommaire

1. [Vue d'ensemble](#1-vue-densemble)
2. [Référentiels de coût](#2-référentiels-de-coût)
   - [matieres](#21-matieres)
   - [epaisseurs_dispo](#22-epaisseurs_dispo)
   - [postes](#23-postes)
   - [vitesses_coupe](#24-vitesses_coupe)
   - [temps_pliage](#25-temps_pliage)
   - [operations](#26-operations)
   - [composants](#27-composants)
   - [traitements](#28-traitements)
   - [parametres](#29-parametres)
3. [Données commerciales](#3-données-commerciales)
   - [clients](#31-clients)
   - [historique_devis](#32-historique_devis)
4. [Données de contrôle](#4-données-de-contrôle)
   - [bornes_controle](#41-bornes_controle)
5. [Règles pour des données simulées crédibles](#5-règles-pour-des-données-simulées-crédibles)
6. [Correspondance avec une vraie usine](#6-correspondance-avec-une-vraie-usine)

---

## 1. Vue d'ensemble

| Table | Rôle | Bloc(s) de coût | Mise à jour (réel) |
|---|---|---|---|
| `matieres` | Prix et densité de chaque nuance | 1. Matière | Mensuelle (cours des métaux) |
| `epaisseurs_dispo` | Épaisseurs et formats de tôle disponibles | 1. Matière | Rare |
| `postes` | Machines et postes : taux horaire, temps de réglage | 2 à 6 | Annuelle (contrôle de gestion) |
| `vitesses_coupe` | Vitesse de coupe et temps d'amorçage par matière × épaisseur | 2. Découpe | Rare (changement de machine) |
| `temps_pliage` | Temps par pli selon la taille de pièce et l'épaisseur | 3. Pliage | Rare (bureau des méthodes) |
| `operations` | Temps standards des opérations (sertissage, taraudage, soudure…) | 4. Soudure, 6. Op. secondaires | Rare (bureau des méthodes) |
| `composants` | Prix des composants achetés (écrous, inserts…) | 6. Composants | Trimestrielle (achats) |
| `traitements` | Prix des traitements de surface sous-traités | 5. Finition | Annuelle (contrats sous-traitants) |
| `parametres` | Marge, rendement de calepinage, facteur K… | Calcul global | Selon la direction |
| `clients` | Marge spécifique par client | Prix final | Au fil de l'eau |
| `historique_devis` | Devis passés | Contrôle de cohérence, recherche de pièces similaires | À chaque devis |
| `bornes_controle` | Plages de valeurs réalistes | Contrôles de fiabilité | Rare |

Schéma des tables : voir [src/generateur_devis/data/README.md](../src/generateur_devis/data/README.md) (diagramme ER maintenu avec le code, d'après `src/generateur_devis/data/tables.py`).

---

## 2. Référentiels de coût

### 2.1 `matieres`

Prix d'achat et densité de chaque matière. La densité sert à passer de la géométrie (mm³) à la masse (kg), et le prix à passer de la masse au coût.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Identifiant, ex. `S235JR` |
| `famille` | texte | `acier`, `inox`, `aluminium` |
| `nuance` | texte | Désignation normalisée |
| `norme` | texte | Norme de référence |
| `densite_kg_dm3` | décimal | Masse volumique |
| `prix_eur_kg` | décimal | Prix d'achat livré |
| `date_maj` | date | Date du prix |
| `fournisseur` | texte | Fournisseur de référence (fictif) |

| id | famille | nuance | norme | densite_kg_dm3 | prix_eur_kg | date_maj |
|---|---|---|---|---|---|---|
| S235JR | acier | S235JR | EN 10025-2 | 7,85 | 1,10 | 2026-11-01 |
| DC01 | acier | DC01 (laminé à froid) | EN 10130 | 7,85 | 1,15 | 2026-11-01 |
| S355MC | acier | S355MC | EN 10149-2 | 7,85 | 1,30 | 2026-11-01 |
| 304L | inox | X2CrNi18-9 (1.4307) | EN 10088-2 | 7,90 | 4,00 | 2026-11-01 |
| 316L | inox | X2CrNiMo17-12-2 (1.4404) | EN 10088-2 | 8,00 | 5,50 | 2026-11-01 |
| 5754 | aluminium | EN AW-5754 H111 | EN 485 | 2,66 | 4,80 | 2026-11-01 |

**Source réelle** : tarifs des distributeurs d'acier, ERP (module achats), indices de cours des métaux.

---

### 2.2 `epaisseurs_dispo`

Épaisseurs réellement stockées pour chaque matière. Si le plan demande une épaisseur absente de cette table, c'est soit une erreur d'extraction, soit un achat spécial à signaler.

| Colonne | Type | Description |
|---|---|---|
| `matiere_id` | texte | Référence vers `matieres` |
| `epaisseur_mm` | décimal | Épaisseur |
| `format_mm` | texte | Format de tôle standard |
| `surcout_pct` | décimal | Surcoût éventuel (épaisseur peu courante) |
| `en_stock` | booléen | Disponible sans délai |

| matiere_id | epaisseurs (mm) | format_mm | surcout_pct | en_stock |
|---|---|---|---|---|
| S235JR | 1 · 1,5 · 2 · 3 · 4 · 5 · 6 · 8 · 10 | 3000 × 1500 | 0 % | oui |
| DC01 | 0,8 · 1 · 1,5 · 2 · 2,5 · 3 | 2500 × 1250 | 0 % | oui |
| 304L | 1 · 1,5 · 2 · 3 · 4 · 5 | 3000 × 1500 | 0 % | oui |
| 316L | 1 · 1,5 · 2 · 3 | 2000 × 1000 | 10 % | non |
| 5754 | 1 · 1,5 · 2 · 3 · 4 · 5 | 3000 × 1500 | 0 % | oui |

(Une ligne par couple matière × épaisseur dans la base ; regroupées ici pour la lisibilité.)

**Source réelle** : gestion de stock (ERP), catalogue du distributeur.

---

### 2.3 `postes`

Chaque machine ou poste de travail, avec son taux horaire chargé et son temps de réglage par lot.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Identifiant du poste |
| `nom` | texte | Libellé |
| `type` | texte | `decoupe`, `pliage`, `soudure`, `sertissage`, `manuel` |
| `taux_horaire_eur_h` | décimal | Taux chargé (machine + opérateur + structure) |
| `temps_reglage_min` | décimal | Temps de réglage / programmation par lot |

| id | nom | type | taux_horaire_eur_h | temps_reglage_min |
|---|---|---|---|---|
| LASER_3KW | Laser fibre 3 kW | decoupe | 120 | 15 |
| PLIEUSE_CN | Presse plieuse CN 100 t | pliage | 70 | 20 |
| SOUDURE_MIG | Poste soudure MIG | soudure | 60 | 15 |
| SERTISSEUSE | Presse à sertir | sertissage | 50 | 10 |
| MANUEL | Poste manuel (ébavurage, taraudage, contrôle) | manuel | 50 | 0 |

**Source réelle** : contrôle de gestion. Le taux se calcule ainsi : charges annuelles du poste ÷ heures productives (voir [logique_metier.md §2.1](logique_metier.md#21-taux-horaire-machine--taux-chargé-)).

---

### 2.4 `vitesses_coupe`

Vitesse de coupe effective et temps d'amorçage, par machine, famille de matière et épaisseur. La vitesse « effective » tient déjà compte des ralentissements dans les angles et les petits contours.

| Colonne | Type | Description |
|---|---|---|
| `poste_id` | texte | Référence vers `postes` |
| `famille` | texte | Famille de matière |
| `epaisseur_mm` | décimal | Épaisseur |
| `vitesse_m_min` | décimal | Vitesse effective |
| `temps_amorcage_s` | décimal | Perçage + déplacement par contour |
| `gaz` | texte | Gaz d'assistance |

| poste_id | famille | epaisseur_mm | vitesse_m_min | temps_amorcage_s | gaz |
|---|---|---|---|---|---|
| LASER_3KW | acier | 1 | 7,0 | 0,7 | O₂ |
| LASER_3KW | acier | 2 | 5,0 | 1,0 | O₂ |
| LASER_3KW | acier | 3 | 3,5 | 1,2 | O₂ |
| LASER_3KW | acier | 5 | 2,2 | 1,5 | O₂ |
| LASER_3KW | acier | 10 | 1,0 | 3,0 | O₂ |
| LASER_3KW | inox | 1 | 6,0 | 0,6 | N₂ |
| LASER_3KW | inox | 2 | 3,5 | 1,0 | N₂ |
| LASER_3KW | inox | 3 | 2,2 | 1,3 | N₂ |
| LASER_3KW | inox | 5 | 1,2 | 2,0 | N₂ |
| LASER_3KW | aluminium | 1 | 7,0 | 0,6 | N₂ |
| LASER_3KW | aluminium | 2 | 4,0 | 1,0 | N₂ |
| LASER_3KW | aluminium | 3 | 2,5 | 1,3 | N₂ |
| LASER_3KW | aluminium | 5 | 1,2 | 2,0 | N₂ |

Pour une épaisseur intermédiaire absente de la table, on interpole entre les deux lignes voisines.

**Source réelle** : abaques du constructeur de la machine, paramètres enregistrés dans le logiciel de programmation laser.

---

### 2.5 `temps_pliage`

Temps par pli selon la taille de la pièce et son épaisseur. Une grande pièce est plus longue à manipuler, et peut demander deux opérateurs.

| Colonne | Type | Description |
|---|---|---|
| `categorie` | texte | `petite`, `moyenne`, `grande` |
| `dim_max_mm` | entier | Plus grande dimension du flan, borne haute |
| `epaisseur_max_mm` | décimal | Épaisseur, borne haute |
| `temps_par_pli_s` | décimal | Temps de cycle par pli |
| `temps_retournement_s` | décimal | Temps ajouté si la pièce doit être retournée |
| `nb_operateurs` | entier | Opérateurs nécessaires |

| categorie | dim_max_mm | epaisseur_max_mm | temps_par_pli_s | temps_retournement_s | nb_operateurs |
|---|---|---|---|---|---|
| petite | 300 | 3 | 8 | 3 | 1 |
| petite | 300 | 10 | 12 | 4 | 1 |
| moyenne | 1000 | 3 | 15 | 6 | 1 |
| moyenne | 1000 | 10 | 20 | 8 | 1 |
| grande | 3000 | 3 | 30 | 15 | 2 |
| grande | 3000 | 10 | 45 | 20 | 2 |

**Source réelle** : temps standards du bureau des méthodes, chronométrages en atelier.

---

### 2.6 `operations`

Temps standards de toutes les autres opérations : soudure, sertissage, taraudage, ébavurage, etc.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Identifiant |
| `nom` | texte | Libellé |
| `poste_id` | texte | Poste sur lequel elle est réalisée |
| `temps_s` | décimal | Temps standard |
| `unite` | texte | Ce à quoi le temps s'applique |

| id | nom | poste_id | temps_s | unite |
|---|---|---|---|---|
| SERTISSAGE | Pose d'un écrou / goujon à sertir | SERTISSEUSE | 12 | par insert |
| TARAUDAGE | Taraudage d'un trou | MANUEL | 20 | par trou |
| FRAISURAGE | Fraisurage d'un trou | MANUEL | 15 | par trou |
| EBAVURAGE_P | Ébavurage petite pièce | MANUEL | 10 | par pièce |
| EBAVURAGE_G | Ébavurage grande pièce | MANUEL | 40 | par pièce |
| SOUDURE_MIG | Cordon de soudure MIG | SOUDURE_MIG | 200 | par mètre (0,3 m/min) |
| POINT_SOUDURE | Point de soudure | SOUDURE_MIG | 5 | par point |
| PREPA_SOUDURE | Pointage, préparation, meulage | SOUDURE_MIG | +50 % | du temps d'arc |
| MARQUAGE | Marquage de la référence | MANUEL | 5 | par pièce |
| CONTROLE | Contrôle dimensionnel | MANUEL | 30 | par pièce contrôlée |

**Source réelle** : gammes de fabrication du bureau des méthodes, chronométrages.

---

### 2.7 `composants`

Composants achetés et ajoutés à la pièce. Ils sont repérés dans la nomenclature du plan (tableau REP / DESIGNATION / QTY).

| Colonne | Type | Description |
|---|---|---|
| `reference` | texte | Référence interne |
| `designation` | texte | Libellé |
| `type` | texte | `ecrou_sertir`, `goujon_sertir`, `entretoise`, `rivet` |
| `filetage` | texte | M4, M5, M6… |
| `matiere` | texte | Acier zingué, inox… |
| `prix_unitaire_eur` | décimal | Prix par pièce |
| `qte_min` | entier | Quantité à partir de laquelle ce prix s'applique |
| `operation_id` | texte | Opération de pose associée |

| reference | designation | type | filetage | matiere | prix_unitaire_eur | qte_min | operation_id |
|---|---|---|---|---|---|---|---|
| ES-M4-A | Écrou à sertir M4 | ecrou_sertir | M4 | acier zingué | 0,15 | 1 | SERTISSAGE |
| ES-M5-A | Écrou à sertir M5 | ecrou_sertir | M5 | acier zingué | 0,18 | 1 | SERTISSAGE |
| ES-M6-A | Écrou à sertir M6 | ecrou_sertir | M6 | acier zingué | 0,20 | 1 | SERTISSAGE |
| ES-M6-A | Écrou à sertir M6 | ecrou_sertir | M6 | acier zingué | 0,15 | 1000 | SERTISSAGE |
| ES-M8-A | Écrou à sertir M8 | ecrou_sertir | M8 | acier zingué | 0,28 | 1 | SERTISSAGE |
| ES-M6-X | Écrou à sertir M6 inox | ecrou_sertir | M6 | inox A2 | 0,45 | 1 | SERTISSAGE |
| GS-M6-A | Goujon à sertir M6 × 16 | goujon_sertir | M6 | acier zingué | 0,25 | 1 | SERTISSAGE |
| ENT-M4-10 | Entretoise à sertir M4 × 10 | entretoise | M4 | acier zingué | 0,30 | 1 | SERTISSAGE |

**Source réelle** : catalogue fournisseur, ERP (module achats). C'est souvent ici que les devis Excel deviennent faux, quand un prix n'a pas été mis à jour.

---

### 2.8 `traitements`

Traitements de surface, généralement sous-traités. Le prix est au m² (ou au kg pour la galvanisation), avec un minimum facturé par lot.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Identifiant |
| `nom` | texte | Libellé |
| `prix` | décimal | Prix unitaire |
| `unite` | texte | `m2` ou `kg` |
| `minimum_lot_eur` | décimal | Minimum facturé par lot |
| `delai_jours` | entier | Délai ajouté au devis |
| `matieres_compatibles` | texte | Familles de matières acceptées |

| id | nom | prix | unite | minimum_lot_eur | delai_jours | matieres_compatibles |
|---|---|---|---|---|---|---|
| PEINTURE_POUDRE | Thermolaquage 1 couche | 35 | m2 | 80 | 5 | acier, aluminium |
| CATAPHORESE | Cataphorèse | 20 | m2 | 100 | 7 | acier |
| ZINGAGE | Zingage électrolytique | 15 | m2 | 60 | 5 | acier |
| GALVA_CHAUD | Galvanisation à chaud | 0,80 | kg | 100 | 10 | acier |
| PASSIVATION | Passivation | 25 | m2 | 80 | 5 | inox |
| ANODISATION | Anodisation naturelle | 30 | m2 | 90 | 7 | aluminium |
| MASQUAGE | Épargne / masquage d'une zone | 0,10 | zone | 0 | 0 | toutes |

**Source réelle** : contrats et grilles tarifaires des sous-traitants.

---

### 2.9 `parametres`

Paramètres globaux du calcul. Ce sont les « boutons » que la direction ou le chargé d'affaires peut ajuster.

| Colonne | Type | Description |
|---|---|---|
| `cle` | texte | Identifiant du paramètre |
| `valeur` | texte | Valeur **stockée en texte** (certains paramètres sont des listes ou du texte) ; le typage (`float`, `list[int]`, `str`) est fait à la lecture par la couche Pydantic, selon la clé |
| `unite` | texte | Unité d'affichage |
| `description` | texte | Rôle du paramètre |

| cle | valeur | unite | description |
|---|---|---|---|
| `marge_defaut` | 0,25 | taux | Taux de marge appliqué au coût (prix = coût ÷ (1 − marge)) |
| `rendement_calepinage` | 0,80 | taux | Part utile de la tôle |
| `facteur_k` | 0,40 | — | Position de la fibre neutre, pour le développé |
| `frais_structure_pct` | 0 | % | Frais additionnels si non inclus dans les taux |
| `minimum_commande_eur` | 0 | € | Prix total plancher d'une commande |
| `paliers_quantite` | 1, 10, 100, 1000 | pièces | Quantités proposées par défaut sur le devis |
| `devise` | EUR | — | Devise du devis |
| `validite_devis_jours` | 30 | jours | Durée de validité du devis |

---

## 3. Données commerciales

### 3.1 `clients`

Clients fictifs, avec une marge spécifique. Si `marge_specifique` est vide, on applique `marge_defaut`. Les quatre dernières colonnes portent les réglages de confidentialité par client (voir [architecture.md §11.3](architecture.md)) : usage de l'IA externe, réutilisation des plans, durée de conservation.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Identifiant |
| `nom` | texte | Nom (fictif) |
| `secteur` | texte | Secteur d'activité |
| `marge_specifique` | décimal | Marge négociée (vide = défaut) |
| `ia_externe_autorisee` | booléen | Le client accepte que ses plans soient traités par une IA externe |
| `reutilisation_autorisee` | booléen | Ses plans peuvent servir d'exemples / de comparaison pour d'autres devis |
| `duree_conservation_plans_jours` | entier | Durée de conservation des plans (défaut 90) |
| `suppression_si_refus` | booléen | Supprimer les plans immédiatement si le client refuse l'IA externe |

| id | nom | secteur | marge_specifique | ia_externe | reutilisation | conservation (j) | suppr. si refus |
|---|---|---|---|---|---|---|---|
| CLI001 | Client Alpha | Poids lourds | 0,18 | oui | oui | 365 | non |
| CLI002 | Client Bêta | Machines agricoles | 0,25 | oui | non | 90 | oui |
| CLI003 | Client Gamma | Ferroviaire | 0,30 | non | non | 90 | oui |
| CLI004 | Client Delta | Agencement | — | oui | oui | 90 | oui |

---

### 3.2 `historique_devis`

Une trentaine de faux devis passés. Cette table a deux usages :

1. **Contrôle de cohérence** : comparer le prix calculé à celui de pièces similaires déjà chiffrées, et signaler un écart anormal.
2. **Recherche de pièces similaires** : l'IA peut retrouver des devis proches (même matière, même taille, même nombre de plis) pour aider le chargé d'affaires.

| Colonne | Type | Description |
|---|---|---|
| `id` | texte | Numéro de devis |
| `date` | date | Date du devis |
| `client_id` | texte | Référence vers `clients` |
| `reference_piece` | texte | Référence de la pièce |
| `designation` | texte | Libellé |
| `matiere_id` | texte | Référence vers `matieres` |
| `epaisseur_mm` | décimal | Épaisseur |
| `flan_l_mm`, `flan_w_mm` | décimal | Dimensions du flan |
| `masse_kg` | décimal | Masse de la pièce |
| `longueur_coupe_mm` | décimal | Longueur de découpe |
| `nb_trous` | entier | Nombre de contours intérieurs |
| `nb_plis` | entier | Nombre de plis |
| `nb_composants` | entier | Nombre de composants |
| `traitement_id` | texte | Traitement (ou vide) |
| `quantite` | entier | Quantité chiffrée |
| `cout_unitaire_eur` | décimal | Coût de revient unitaire |
| `prix_unitaire_eur` | décimal | Prix proposé |
| `statut` | texte | `accepte`, `refuse`, `en_attente` |

| id | date | client_id | designation | matiere_id | ep. | flan (mm) | plis | trous | comp. | trait. | qté | coût € | prix € | statut |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D-2026-0012 | 2026-03-14 | CLI001 | Patte de fixation | S235JR | 3 | 120 × 40 | 1 | 2 | 0 | ZINGAGE | 500 | 1,05 | 1,28 | accepte |
| D-2026-0027 | 2026-05-02 | CLI002 | Capot | DC01 | 1,5 | 600 × 400 | 4 | 12 | 4 | PEINTURE_POUDRE | 50 | 24,60 | 32,80 | accepte |
| D-2026-0041 | 2026-07-21 | CLI003 | Support inox | 304L | 2 | 150 × 90 | 2 | 4 | 2 | PASSIVATION | 200 | 5,90 | 8,43 | refuse |
| … | | | | | | | | | | | | | | |

**Comment les générer** : calculer chaque devis avec le moteur, puis appliquer un bruit aléatoire de ±10–15 % et des prix matière légèrement différents selon la date. Sans ce bruit, l'historique serait parfaitement aligné sur les formules, et le contrôle par comparaison ne prouverait rien. On peut aussi y glisser 2 ou 3 devis volontairement aberrants pour démontrer la détection.

**Source réelle** : les fichiers Excel de devis existants. C'est la donnée la plus précieuse à récupérer en V2, car elle permet de calibrer les paramètres sur la réalité de l'usine.

---

## 4. Données de contrôle

### 4.1 `bornes_controle`

Plages de valeurs réalistes. Elles servent à vérifier les données extraites du plan, les paramètres saisis et le prix final (voir [logique_metier.md §6](logique_metier.md#6-contrôles-de-cohérence)).

| Colonne | Type | Description |
|---|---|---|
| `champ` | texte | Valeur contrôlée |
| `min` | décimal | Borne basse |
| `max` | décimal | Borne haute |
| `niveau` | texte | `alerte` (à vérifier) ou `bloquant` (devis impossible) |
| `message` | texte | Message affiché à l'utilisateur |

| champ | min | max | niveau | message |
|---|---|---|---|---|
| epaisseur_mm | 0,5 | 20 | bloquant | Épaisseur hors capacité atelier |
| flan_dim_max_mm | 10 | 3000 | bloquant | Pièce plus grande que le format de tôle |
| ratio_surface_dev / surface_vue | 0,7 | 3,0 | alerte | Surface développée incohérente avec les vues |
| ratio_longueur_coupe / périmètre_flan | 0,7 | 10 | alerte | Longueur de découpe incohérente |
| ecart_masse_calculee_pct | −15 | 15 | alerte | Masse incohérente avec surface × épaisseur |
| prix_eur_kg (masse > 1 kg) | 2 | 50 | alerte | Prix au kg inhabituel |
| prix_eur_kg (masse ≤ 1 kg) | 2 | 150 | alerte | Prix au kg inhabituel pour une petite pièce |
| part_matiere_pct (qté ≥ 100) | 3 | 70 | alerte | Répartition des coûts inhabituelle |
| ecart_historique_pct | −30 | 30 | alerte | Écart important avec des pièces similaires |
| marge | 0,05 | 0,50 | alerte | Marge hors politique commerciale |

---

## 5. Règles pour des données simulées crédibles

Pour que le cas simulé reste réaliste et défendable :

1. **Partir d'ordres de grandeur sourcés.** Chaque valeur par défaut vient d'une fourchette publique (sources dans [logique_metier.md §11](logique_metier.md#11-sources)).
2. **Garder des valeurs cohérentes entre elles.**
   - La vitesse de coupe baisse quand l'épaisseur augmente.
   - L'inox se coupe plus lentement que l'acier.
   - L'inox et l'aluminium coûtent 3 à 5 fois plus cher au kg que l'acier.
   - Le temps par pli augmente avec la taille et l'épaisseur de la pièce.
   - Le prix unitaire d'un composant baisse avec la quantité.
3. **Dater les prix** (`date_maj`) pour montrer qu'ils évoluent et qu'un prix trop ancien doit être signalé.
4. **Vérifier sur un exemple de référence** : avec ces valeurs, piece_003 doit retomber sur le calcul du guide (≈ 2,20 € de coût, 2,93 € de prix pour 100 pièces).
5. **Ne jamais coder une valeur en dur** dans le moteur. Tout chiffre utilisé dans un calcul doit venir de ces tables, pour rester modifiable et traçable.

---

## 6. Correspondance avec une vraie usine

| Table simulée | Où la donnée existe dans l'usine | Qui la tient à jour |
|---|---|---|
| `matieres`, `epaisseurs_dispo` | ERP (achats / stock), tarifs distributeurs | Acheteur |
| `postes` | Contrôle de gestion | Contrôleur de gestion |
| `vitesses_coupe` | Logiciel de programmation laser, abaques constructeur | Programmeur CN |
| `temps_pliage`, `operations` | Gammes de fabrication, chronométrages | Bureau des méthodes |
| `composants` | ERP (achats), catalogue fournisseur | Acheteur |
| `traitements` | Contrats sous-traitants | Acheteur |
| `parametres`, `clients` | Politique commerciale | Direction commerciale |
| `historique_devis` | Fichiers Excel de devis existants | Chargés d'affaires |
| `bornes_controle` | Connaissance métier | Bureau des méthodes + commercial |

Le passage de la V1 à une vraie mise en production consiste essentiellement à **remplacer ces valeurs simulées par les données réelles** de chaque usine. Le moteur de calcul, lui, ne change pas.
