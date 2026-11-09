# Résultats de l'évaluation de l'extraction

Résultats obtenus avec le protocole décrit dans [evaluation.md](evaluation.md).

> **État au 9 novembre 2026** : trois modèles évalués sur tous les jeux de test (cadsy, ecado, plans de tôlerie générés en PDF propre, scan et photo, plans volontairement erronés) : Claude Sonnet 5.5, Gemini 2.5 Flash et Qwen3.8 27B (open source). Plans incohérents : Claude et Qwen.

---

## 1. Conditions

| Élément | Valeur |
|---|---|
| Modèles | Claude Sonnet 5.5 (`claude-code:sonnet`, abonnement Claude) ; comparaison : Gemini 2.5 Flash (`openrouter:google/gemini-2.5-flash`) et Qwen3.8 27B (`nous:qwen/qwen3.8-27b`, abonnement Nous Research) |
| Prompt | v2 ([prompt.py](../src/generateur_devis/extraction/prompt.py)) |
| Format de la pièce | 1.2 ([piece.py](../src/generateur_devis/schema/piece.py)) |
| Images | Jeux publics : plans d'origine (niveau 1 : image propre, sans texte PDF). Jeu A : niveaux 0 (PDF propre), 2 (scan) et 3 (photo) |
| Jeux de test | cadsy : 30 plans · ecado : 40 plans · tôlerie générée : 50 plans × 3 niveaux + 16 plans erronés + 12 plans incohérents (jamais utilisés pendant la mise au point) |
| Coût | Claude : ~3,40 $ en équivalent API pour les 70 plans publics, ~8,50 $ pour les 166 lectures du jeu A, pris sur les quotas de l'abonnement. Gemini : ~1,90 $ pour les 236 lectures (payé sur OpenRouter). Qwen : ~5,70 $ en équivalent (abonnement Nous) |
| Durée | ~20 s par plan (Claude), ~10 s (Gemini), ~55 s (Qwen) |
| Réponses valides | Claude 236 / 236 (8 appels photo relancés après une coupure de quota, sans effet sur le contenu) ; Gemini 232 / 236 ; Qwen 236 / 236 (2 relances après délai réseau) |

---

## 2. Résultats sur les jeux de test

Composition des jeux et exemples en image (niveaux de qualité, plans erronés et incohérents) : [jeux_de_test.md](jeux_de_test.md).

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

### Plans de tôlerie générés (jeu A) — test, 50 plans × 3 niveaux

Plans PDF générés avec leur bonne réponse (voir [evaluation.md §3.1](evaluation.md#31-jeu-a--plans-de-tôlerie-générés-référence-principale)) : formes plaque, L, U, Z et chapeau, trous, chanfreins et rayons de coin, écrous et goujons à sertir, traitement, notes en français ou en anglais. Les mêmes 50 plans sont lus à trois niveaux (voir [evaluation.md §5](evaluation.md#5-niveaux-de-dégradation)) : PDF propre (texte + image), scan, photo.

| Champ | PDF propre | Scan | Photo |
|---|---|---|---|
| Cartouche (référence, désignation, indice), unités | 100 % | 100 % | 100 % |
| Matière, famille, **épaisseur** | 100 % | 100 % | 100 % |
| **Profil de pliage** (ailes, angles) | 100 % | 100 % | **96 %** (2 cotes mal lues) |
| Nombre de plis | 100 % | 100 % | 100 % |
| Encombrement | 100 % | **92 %** | **94 %** |
| Traitement (désignation / type) | 98 % / 100 % | 100 % | 100 % |
| Tolérance générale (y compris 11 absences) | 100 % | 100 % | 100 % |
| Trous (67), coins (60), composants à sertir (24) | 100 % | 100 % | 100 % |
| Notes (123) | 99 % | 99 % | 100 % |
| Cotes (339) | 100 % | 100 % | 100 % |

IC 95 % : 93 – 100 % pour un champ à 100 % sur 50 plans ; 81 – 97 % pour 92 %.

**Analyse des écarts**
- **Photo, profil de pliage** : deux cotes mal lues (98 lu 96, 77,5 lu 94). C'est l'erreur la plus gênante : elle est **silencieuse** (confiance élevée, aucune anomalie) et change le développé, donc le prix matière.
- **Encombrement** (scan et photo) : surtout une dimension **non donnée** quand elle n'est pas cotée directement (hauteur d'un Z par exemple), plus deux lectures fausses en photo. Ce champ est recalculable par le code à partir du profil et de la largeur : on peut s'en passer.
- **Zone d'épargne** (3 plans) : « THREADS » est traduit en « filetages ». Le sens est juste ; c'est la comparaison mot à mot qui le refuse.
- **Écarts de rangement**, sans conséquence pour le devis : « NO PAINT ON THREADS » recopiée aussi en note ; « FINISH: PASSIVATION » gardé avec son libellé.

**À retenir** : sur ces plans, le passage du PDF propre à la photo ne coûte presque rien en lecture du texte, des trous, des composants et des cotes. Les seules pertes portent sur des **chiffres de cotes mal lus** en photo (environ 1 plan sur 25). C'est ce que la validation humaine doit attraper.

### Plans volontairement erronés (niveau E) — test, 16 plans

| Erreur introduite | Signalée par l'IA (comptage automatique) |
|---|---|
| Matière absente (« — » dans le cartouche) | 4 / 4 |
| Épaisseur absente (« — » dans le cartouche) | 4 / 4 |
| Cote d'aile manquante (non retrouvable) | 4 / 4 |
| Cotes contradictoires (encombrement ≠ somme des ailes, écart de 5 à 20 mm) | 4 / 4 |
| **Total** | **16 / 16** (IC 95 % : 81 – 100 %) |

Aucune valeur inventée : la matière et l'épaisseur absentes sont laissées vides avec une anomalie ; la longueur d'aile manquante n'est pas mesurée sur le dessin ; les contradictions sont décrites avec les deux valeurs (ex. « Les cotes 120,5 et 140,5 couvrent la même étendue sur la vue de côté (même origine, même extrémité) mais ont des valeurs différentes »).

**Relecture manuelle des signalements** : le comptage automatique accepte toute anomalie qui touche le bon champ (ou, pour les contradictions, toute anomalie de type « incohérence »). Relus un par un, **15 signalements sur 16 désignent bien l'erreur** ; le seizième (test-e007) signale une incohérence, mais sur un autre point du plan. Le comptage automatique est donc légèrement optimiste ; les chiffres relus sont donnés dans la comparaison ci-dessous.

### Plans incohérents — test, 12 plans

Informations lisibles mais invraisemblables, qu'il faut repérer en croisant deux informations ou en connaissant le métier. Exemples en image dans [jeux_de_test.md](jeux_de_test.md#4-plans-incohérents).

| Incohérence | Claude Sonnet 5.5 | Qwen3.8 27B |
|---|---|---|
| Quantité de trous fausse (« 6x Ø8,5 » mais 2 trous dessinés) | 4 / 4 | 3 / 4 |
| Trou coté hors de la pièce (position 178 sur une plaque de 126) | 4 / 4 | 3 / 4 |
| Traitement impossible (anodisation sur acier, galvanisation sur aluminium ou inox) | 4 / 4 | 1 / 4 |
| **Total** (relu un par un) | **12 / 12** (IC 95 % : 76 – 100 %) | 7 / 12 |

- Claude explique chaque problème : « La cote indique 6x Ø8.5 mais seuls 2 trous sont visibles », « l'anodisation ne s'applique pas à l'acier (réservée à l'aluminium) ».
- Les deux modèles **recopient la quantité écrite** (6 trous) et non celle du dessin (2) : sans le signalement, le devis compterait 6 perçages. Le signalement est donc indispensable, pas un bonus.
- Qwen voit les incohérences géométriques mais rarement les incohérences métier (traitement / matière).
- Gemini 2.5 Flash n'a pas été évalué sur ce jeu (payant sur OpenRouter, ~0,10 $).

### Comparaison des modèles

Mêmes jeux de test, même prompt v2, trois modèles :
- **Claude Sonnet 5.5** (haut de gamme, `claude-code:sonnet`, abonnement Claude) ;
- **Gemini 2.5 Flash** (économique, `openrouter:google/gemini-2.5-flash`) ;
- **Qwen3.8 27B** (open source, poids publics, `nous:qwen/qwen3.8-27b`, abonnement Nous Research).

Les scores portent sur les réponses valides. Tôlerie : PDF propre / scan / photo.

| Jeu / champ | Claude Sonnet 5.5 | Gemini 2.5 Flash | Qwen3.8 27B |
|---|---|---|---|
| **Tôlerie : profil de pliage** | **100 / 100 / 96 %** | 78 / 75 / 72 % | 84 / 88 / 78 % ¹ |
| Tôlerie : nombre de plis | 100 / 100 / 100 % | 84 / 85 / 84 % | 84 / 90 / 82 % ¹ |
| Tôlerie : encombrement | 100 / 92 / 94 % | 80 / 77 / 76 % | 88 / 82 / 88 % |
| Tôlerie : type de traitement | 100 / 100 / 100 % | 86 / 90 / 90 % | 94 / 92 / 92 % |
| Tôlerie : matière, épaisseur, trous, cotes | 100 % | 98 – 100 % | 97 – 100 % |
| Tôlerie : coins (précision) | 100 % | 88 – 97 % | 83 – 94 % (coins en trop) |
| **Plans erronés signalés** (automatique / relu) | **16 / 16 — 15 / 16** | 7 / 15 — 7 / 15 | 14 / 16 — 13 / 16 |
| cadsy : rappel des cotes | 98 % | 81 % | 94 % (précision 84 %) |
| cadsy : type de tolérance géométrique | 54 % | 39 % | 45 % |
| ecado : soudures | 98 % | 87 % | 82 % |
| ecado : cotes | 97 % | 86 % | 79 % |
| ecado : type de tolérance géométrique | 69 % | 41 % | 36 % |
| Réponses valides (JSON conforme) | 236 / 236 | 232 / 236 | 236 / 236 ² |
| **Coût par plan** (équivalent API) | ~0,05 $ | **~0,008 $** | ~0,024 $ |
| Durée par plan | ~20 s | ~10 s | ~55 s (modèle qui « réfléchit » avant de répondre) |

¹ Dont 4 plaques sans pli pour lesquelles Qwen ne donne pas de profil : comptées « manquant », mais sans conséquence pour le devis (aucun pli). Sans elles, le profil de pliage serait à 92 / 96 / 86 %.
² Après relance de 2 appels interrompus par un délai réseau.

**Analyse des erreurs**
- **Pièces à 4 plis (chapeau)** : Gemini et Qwen gardent souvent 3 ailes sur 5 et oublient les ailes verticales (2 plis au lieu de 4). C'est l'erreur la plus coûteuse pour le devis : nombre de plis et développé faux. Qwen le signale parfois par une anomalie, Gemini jamais.
- **Plans erronés** : les trois modèles signalent la matière et l'épaisseur absentes. Pour les erreurs de cotes, Gemini **invente** la longueur d'aile manquante (4 / 4) et **ne voit aucune** contradiction (0 / 4) ; Qwen en détecte la plupart (aile manquante 3 / 4 dont 1 ambigu, contradictions 3 / 4) ; Claude les détecte toutes sauf un cas ambigu.
- **Type de traitement** : Gemini et Qwen rangent parfois « thermolaquage » en « peinture » (proche, mais faux pour le prix).
- **Texte du plan** (cartouche, matière, épaisseur, notes) : bien lu par les trois modèles.

**À retenir** : Claude Sonnet est nettement meilleur sur ce qui coûte cher en cas d'erreur (géométrie des plis, signalement des problèmes) et reste peu coûteux (~0,05 $ par plan, négligeable devant le coût d'une erreur de devis) : **c'est le modèle retenu pour la V1**. Qwen3.8 27B est le meilleur des deux autres, notamment pour signaler les problèmes : c'est le **repli** si les données ne doivent pas sortir de l'entreprise (modèle à poids publics, hébergeable en interne). Gemini Flash ne suffit que pour le texte du plan.

### Plans de tôlerie générés — développement, 15 plans

Mêmes conclusions que sur le test : 100 % partout en PDF propre, sauf l'encombrement (87 %) ; scan et photo quasi identiques ; 8 / 8 plans erronés signalés.

### Mise au point (jeux de développement)

Sur piece_003 (seul vrai plan de tôlerie, utilisé pour écrire le prompt) : tous les champs justes (épaisseur, encombrement, profil en Z avec 2 plis à 90°, trous, chanfreins, écrous à sertir, tolérances), matière absente correctement signalée. Une note sur quatre manquée.

---

## 3. Lecture des résultats

**Ce qui est fiable**
- Sur les plans de tôlerie générés, **tout ce qui sert au devis** (matière, épaisseur, profil de pliage, trous, coins, composants, traitement) est lu à 96 – 100 %, y compris sur scan et photo.
- Les **erreurs du plan** (information absente, cotes contradictoires) sont signalées dans 15 cas sur 16 et les **incohérences** (quantité, position, traitement impossible) dans 12 cas sur 12 (relecture manuelle), sans invention.
- Le **texte du plan** (cartouche, matière, traitement, notes, unités) est lu quasiment sans erreur.
- Les **cotes** sont retrouvées à 97 – 98 %, sur des plans simples comme sur des plans CAO denses.
- Les **valeurs** des tolérances géométriques et des états de surface sont toutes justes.
- Le modèle **n'invente pas** : quand la tolérance générale est absente (30 plans ecado), il laisse le champ vide.

**Ce qui ne l'est pas**
- Le **type de tolérance géométrique** (lecture du symbole : symétrie, rectitude, cylindricité…) n'est juste qu'une fois sur deux à deux fois sur trois. Dans la grande majorité des erreurs, le modèle répond « autre » plutôt qu'un mauvais type : il signale son incertitude au lieu d'inventer. Pour le devis, la **valeur** (le niveau d'exigence) compte davantage que le type.

- Sur photo, quelques **chiffres de cotes mal lus sans signalement** (2 profils sur 50) : la confiance annoncée ne suffit pas à les repérer.

**Limites de ces chiffres**
- Les plans de tôlerie sont **générés** : plus réguliers que de vrais plans (mise en page, polices, cotation complète, plis à 90° seulement). **piece_003 est le seul vrai plan de tôlerie disponible** et aucun autre n'est accessible pour cet exercice. Les scores du jeu A sont donc un **plafond**, pas une prévision : la qualité réelle sera à mesurer sur les premiers plans clients, pendant une phase pilote où chaque extraction est validée par un humain.
- Les pièces à 4 plis (5 plans) et les zones d'épargne (3 plans) sont peu nombreuses : les écarts sur ces cas sont nets mais mesurés sur peu de plans.
- Scan et photo sont **simulés** : pas de pliure du papier, de reflet, d'annotation manuscrite ni de photo partielle.
- Les jeux publics (cadsy, ecado) ne contiennent pas de plis ; ils mesurent surtout la lecture du texte et des cotes.
- Précision des cotes cadsy (84 %) : la bonne réponse ignore les annotations composées (profondeurs de perçage, oblongs), que le modèle lit pourtant. Une partie des cotes « en trop » sont donc justes.
- Trois modèles (haut de gamme, économique, open source), un seul prompt (v2, écrit et mis au point avec Claude) : les deux autres modèles pourraient gagner un peu avec un prompt adapté.

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
| Dégradations et niveau E | Scan, photo et plans erronés ajoutés (prompt inchangé) | Scan / photo : seul l'encombrement baisse (87 – 93 %) ; plans erronés 8 / 8 signalés |

---

## 6. Prochaines étapes

1. **Contrôles par le code** dans l'outil : recalculer l'encombrement à partir du profil, vérifier la somme des ailes, compter les trous, vérifier la compatibilité matière / traitement. Ils doublent les signalements de l'IA et attrapent les cotes mal lues en photo.
2. **Phase pilote** : mesurer la qualité sur les premiers vrais plans clients, à partir des corrections faites dans le formulaire de validation.
