"""Étude de la qualité de l'extraction (voir docs/evaluation.md et docs/resultats.md).

Code séparé de l'application : il utilise l'extraction de `generateur_devis` pour mesurer
exactement ce qui sera livré, mais l'application n'importe jamais ce paquet.

- `generateur` : plans de tôlerie générés avec leur bonne réponse ;
- `degradations` : scan et photo simulés ;
- `jeux` : chargement des jeux (cadsy, ecado, privé, tôlerie) ;
- `comparaison`, `executer` : comparaison champ par champ, synthèse, résultats.
"""
