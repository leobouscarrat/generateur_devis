# Résultats de l'évaluation de l'extraction

Résultats obtenus avec le protocole décrit dans [evaluation.md](evaluation.md).

> **État au 8 novembre 2026** : un seul modèle évalué (Claude Sonnet 5.5, via l'abonnement Claude). Jeux publics cadsy et ecado : développement et test. Plans de tôlerie générés (jeu A) : développement uniquement. Les dégradations (scan, photo) et la comparaison avec d'autres modèles restent à faire.

---

## 1. Conditions

| Élément | Valeur |
|---|---|
| Modèle | Claude Sonnet 5.5 (`claude-code:sonnet`, abonnement Claude) |
| Prompt | v2 ([prompt.py](../src/generateur_devis/extraction/prompt.py)) |
| Format de la pièce | 1.2 ([piece.py](../src/generateur_devis/schema/piece.py)) |
| Images | Plans d'origine des jeux (niveau 1 : image propre, sans texte PDF) |
| Jeux de test | cadsy : 30 plans · ecado : 40 plans (jamais utilisés pendant la mise au point) |
| Coût | ~3,40 $ en équivalent API pour les 70 plans, pris sur les quotas de l'abonnement |
| Durée | ~20 s par plan |
| Réponses valides | 70 / 70, sans relance |

---

## 2. Résultats sur les jeux de test

### ecado — 40 plans orientés devis (cartouche, matière, traitement, notes)

| Champ | Score | IC 95 % |
|---|---|---|
| Unités (mm / in) | 100 % | 91 – 100 % |
| Référence, désignation, indice | 100 % | 91 – 100 % |
| Matière (désignation et famille) | 100 % | 91 – 100 % |
| Traitement | 98 % | 87 – 100 % |
| Tolérance générale (y compris absence correctement signalée) | 100 % | 91 – 100 % |
| Soudures (nombre) | 98 % | 87 – 100 % |
| États de surface | 100 % (71 / 71) | 95 – 100 % |
| Tolérances géométriques : valeur | 100 % (67 / 67) | 95 – 100 % |
| Tolérances géométriques : type (symbole) | **69 %** | 57 – 78 % |
| Notes | 100 % (88 / 88) | 96 – 100 % |
| Cotes | 97 % (226 / 228) | 94 – 99 % |

### cadsy — 30 plans réalistes (rendu CAO, cotation dense)

| Champ | Score | IC 95 % |
|---|---|---|
| Tolérance générale | 100 % | 89 – 100 % |
| Cotes : rappel | 98 % (361 / 368) | 95 – 99 % |
| Cotes : précision | 84 % | — (indicative, voir ci-dessous) |
| Tolérances géométriques : valeur | 100 % (87 / 87) | 96 – 100 % |
| Tolérances géométriques : type (symbole) | **54 %** | 44 – 64 % |

### Plans de tôlerie générés (jeu A) — développement, 15 plans

Plans PDF générés avec leur bonne réponse (voir [evaluation.md §3.1](evaluation.md#31-jeu-a--plans-de-tôlerie-générés-référence-principale)) : formes plaque, L, U, Z et chapeau, trous, chanfreins et rayons de coin, écrous et goujons à sertir, traitement, notes en français ou en anglais.

| Champ | Score |
|---|---|
| Cartouche (référence, désignation, indice), unités | 100 % |
| Matière, famille, **épaisseur** | 100 % |
| **Profil de pliage** (ailes, angles) et nombre de plis | 100 % |
| Encombrement | 87 % (13 / 15) |
| Traitement, tolérance générale (y compris absences) | 100 % |
| Trous (29), coins (18), composants à sertir (8) | 100 % |
| Notes | 100 % (32 / 32) |
| Cotes | 100 % (102 / 102) |

Écarts : deux erreurs d'encombrement (une dimension manquante, une dimension confondue avec une cote de position de trou) ; une zone d'épargne traduite (« filetages » au lieu de « THREADS » écrit sur le plan).

Ces plans sont propres (PDF vectoriel) : les scores sur scans et photos seront plus bas. Le jeu de test (50 plans) n'a pas encore été lancé.

### Mise au point (jeux de développement)

Sur piece_003 (seul vrai plan de tôlerie, utilisé pour écrire le prompt) : tous les champs justes (épaisseur, encombrement, profil en Z avec 2 plis à 90°, trous, chanfreins, écrous à sertir, tolérances), matière absente correctement signalée. Une note sur quatre manquée.

---

## 3. Lecture des résultats

**Ce qui est fiable**
- Le **texte du plan** (cartouche, matière, traitement, notes, unités) est lu quasiment sans erreur.
- Les **cotes** sont retrouvées à 97 – 98 %, sur des plans simples comme sur des plans CAO denses.
- Les **valeurs** des tolérances géométriques et des états de surface sont toutes justes.
- Le modèle **n'invente pas** : quand la tolérance générale est absente (30 plans ecado), il laisse le champ vide.

**Ce qui ne l'est pas**
- Le **type de tolérance géométrique** (lecture du symbole : symétrie, rectitude, cylindricité…) n'est juste qu'une fois sur deux à deux fois sur trois. Dans la grande majorité des erreurs, le modèle répond « autre » plutôt qu'un mauvais type : il signale son incertitude au lieu d'inventer. Pour le devis, la **valeur** (le niveau d'exigence) compte davantage que le type.

**Limites de ces chiffres**
- Ces jeux ne contiennent **ni plis ni pièces de tôlerie** : la lecture du profil de pliage, de l'épaisseur et des composants n'est mesurée que sur piece_003. C'est le rôle du jeu A (plans de tôlerie générés), encore à construire.
- Images **propres** uniquement : l'effet d'un scan ou d'une photo reste à mesurer.
- Précision des cotes cadsy (84 %) : la bonne réponse ignore les annotations composées (profondeurs de perçage, oblongs), que le modèle lit pourtant. Une partie des cotes « en trop » sont donc justes.
- Un seul modèle : pas encore de comparaison qualité / coût.

---

## 4. Corrections apportées aux bonnes réponses

Deux erreurs de **conversion des bonnes réponses** ont été trouvées en analysant les résultats de test, et corrigées. Elles ne touchent ni le prompt ni le modèle : les scores ont été recalculés à partir des réponses déjà obtenues, sans nouvel appel.

| Jeu | Problème | Effet avant correction |
|---|---|---|
| ecado | Les notes « GENERAL TOLERANCE » étaient comptées comme notes, alors que la consigne v2 les range dans le champ `tolerance_generale` (juste à 100 %) | Notes : 90 % au lieu de 100 % |
| cadsy | Deux cadres de tolérance empilés sont regroupés dans une seule annotation ; la conversion n'en comptait qu'un | 16 tolérances comptées « en trop » |

De même, l'annotation de piece_003 a été alignée sur les conventions v2 (notes de tolérance et d'épargne rangées dans leurs champs, première langue d'un plan bilingue).

---

## 5. Historique des versions

| Version | Changement | Effet mesuré (jeux de développement) |
|---|---|---|
| Prompt v1 / format 1.1 | Version initiale | Soudures isolées manquées (3 / 5 plans ecado) ; états de surface et tolérances géométriques rangés dans les notes |
| Prompt v2 / format 1.2 | Champs `tolerances_geometriques` et `etats_surface` ; consigne sur les soudures isolées et sur le rangement des informations | Soudures 5 / 5 ; notes ecado sans éléments en trop |
| Générateur, 1re version | Ailes cotées à l'axe de la tôle, avec encombrement extérieur en plus | Profil de pliage juste à 33 % : le modèle lit les cotes extérieures, convention courante en tôlerie. Ambiguïté du générateur, pas erreur du modèle |
| Générateur, 2e version | Ailes cotées à l'extérieur, sans cote redondante | Profil de pliage juste à 100 % |

---

## 6. Prochaines étapes

1. **Jeu A, test** : lancer les 50 plans de test.
2. **Dégradations** (scan, photo, plans erronés) sur les jeux existants.
3. **Autres modèles** (modèle économique, modèle open source) pour la comparaison qualité / coût.
