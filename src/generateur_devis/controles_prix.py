"""Contrôles de cohérence du chiffrage (issue #16, logique_metier §6).

Évalués sur le **résultat du chiffrage** (prix et coûts par palier), après
le moteur de calcul — les contrôles portant sur l'extraction (surface,
longueur de coupe, masse, amorçages) sont couverts en amont et hors scope.

Contrôles V1 (bornes lues dans ``bornes_controle`` via ``acces.get_bornes``,
aucune valeur en dur ; une borne absente → contrôle ignoré silencieusement) :

- **prix au kg** aux paliers de série (quantité ≥ 100, §6 « en série »),
  borne selon la masse nette (``> 1 kg`` ou ``≤ 1 kg``) — une très petite
  pièce est naturellement chère au kg (§8.5) ;
- **part matière** du coût de revient, paliers de quantité ≥ 100
  (borne ``part_matiere_pct_qte_gte_100``) ;
- **prix matière trop ancien** : ``matieres.date_maj`` plus vieille que le
  paramètre ``prix_matiere_max_age_jours`` (pas d'alerte si date absente) ;
- **écart avec l'historique** : coût unitaire du palier vs moyenne des
  devis similaires de même matière et quantité proche (×½ à ×2) — pas
  d'alerte s'il n'y a aucun similaire.

Ne produit que des **alertes** (modèle ``Constat`` de ``faisabilite``),
jamais de blocage : le blocage est déjà géré par la faisabilité en amont.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from generateur_devis.calcul_prix import Chiffrage
from generateur_devis.data.acces import get_bornes, get_parametre, list_historique_similaires
from generateur_devis.faisabilite import Constat
from generateur_devis.geometrie import Flan
from generateur_devis.schema.piece import PieceExtraite


def _alerte(regle: str, message: str, champ: str | None = None) -> Constat:
    return Constat(regle=regle, severite="alerte", message=message, champ=champ)


def evaluer_controles_prix(
    chiffrage: Chiffrage,
    piece: PieceExtraite,
    flan: Flan,
    matiere_id: str,
    session: Session,
) -> list[Constat]:
    """Évalue les contrôles de cohérence du chiffrage (alertes seulement).

    Args:
        chiffrage: résultat de ``calcul_prix.chiffrer``.
        piece: pièce chiffrée (conservée pour traçabilité des champs).
        flan: flan de la pièce (masse nette pour le prix au kg).
        matiere_id: matière du chiffrage (date du prix, historique).
        session: session SQLAlchemy sur la base de référence.

    Returns:
        Les alertes, dans l'ordre d'évaluation ; liste vide si tout est
        cohérent.
    """
    constats: list[Constat] = []
    bornes = {b.champ: b for b in get_bornes(session)}
    masse_kg = flan.masse_nette_kg

    # --- Prix au kg, par palier, borne selon la masse ----------------------
    champ = "prix_eur_kg_masse_gt_1kg" if masse_kg > 1.0 else "prix_eur_kg_masse_le_1kg"
    borne = bornes.get(champ)
    if borne is not None and masse_kg > 0:
        for palier in chiffrage.paliers:
            if palier.quantite < 100:
                continue  # §6 : la fourchette €/kg s'applique « en série »
            prix_kg = palier.prix_unitaire_eur / masse_kg
            if prix_kg < borne.min or prix_kg > borne.max:
                constats.append(
                    _alerte(
                        "prix_au_kg",
                        f"Palier {palier.quantite} : {prix_kg:.0f} €/kg hors borne "
                        f"[{borne.min:g}, {borne.max:g}] ({borne.message}).",
                        champ="paliers.prix_unitaire_eur",
                    )
                )

    # --- Part matière du coût de revient, paliers Q ≥ 100 -------------------
    borne = bornes.get("part_matiere_pct_qte_gte_100")
    if borne is not None:
        cout_matiere = chiffrage.blocs_1_3.matiere.cout_variable_eur
        for palier in chiffrage.paliers:
            if palier.quantite < 100 or palier.cout_unitaire_eur <= 0:
                continue
            part = cout_matiere / palier.cout_unitaire_eur * 100.0
            if part < borne.min or part > borne.max:
                constats.append(
                    _alerte(
                        "part_matiere",
                        f"Palier {palier.quantite} : part matière {part:.0f} % hors borne "
                        f"[{borne.min:g}, {borne.max:g}] ({borne.message}).",
                        champ="blocs.matiere",
                    )
                )

    # --- Prix matière trop ancien -------------------------------------------
    date_prix = next(
        (ligne.date_prix for ligne in chiffrage.trace if ligne.bloc == "matiere"), None
    )
    if date_prix is not None:
        max_age = int(get_parametre("prix_matiere_max_age_jours", session))
        age = (date.today() - date_prix).days
        if age > max_age:
            constats.append(
                _alerte(
                    "prix_matiere_ancien",
                    f"Prix de {matiere_id} vieux de {age} jours (> {max_age}) : "
                    "à revalider avant chiffrage.",
                    champ="matiere.prix",
                )
            )

    # --- Écart avec l'historique, par palier (quantité proche ×½ à ×2) ------
    borne = bornes.get("ecart_historique_pct")
    if borne is not None:
        for palier in chiffrage.paliers:
            similaires = list_historique_similaires(
                session,
                matiere_id=matiere_id,
                quantite_min=max(1, palier.quantite // 2),
                quantite_max=palier.quantite * 2,
            )
            if not similaires:
                continue
            moyenne = sum(h.cout_unitaire_eur for h in similaires) / len(similaires)
            if moyenne <= 0:
                continue
            ecart = (palier.cout_unitaire_eur - moyenne) / moyenne * 100.0
            if ecart < borne.min or ecart > borne.max:
                constats.append(
                    _alerte(
                        "ecart_historique",
                        f"Palier {palier.quantite} : coût {palier.cout_unitaire_eur:.2f} € "
                        f"à {ecart:+.0f} % de la moyenne des {len(similaires)} devis "
                        f"similaires ({moyenne:.2f} €) ({borne.message}).",
                        champ="paliers.cout_unitaire_eur",
                    )
                )

    return constats
