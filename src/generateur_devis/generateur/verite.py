"""Bonne réponse d'une pièce générée, au format de la pièce."""

from generateur_devis.generateur.modele import COMPOSANTS, Geometrie, SpecPiece
from generateur_devis.schema import (
    Aile,
    Champ,
    CoinCoupe,
    Composant,
    Contours,
    Cote,
    Encombrement,
    Identification,
    Matiere,
    Note,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Traitement,
    Trou,
)


def verite(spec: SpecPiece, geo: Geometrie, cotes: list[Cote]) -> PieceExtraite:
    elements: list = []
    for i, longueur in enumerate(spec.ailes):
        elements.append(Aile(longueur=longueur))
        if i < len(spec.virages):
            elements.append(Pli(angle=90, sens="haut" if spec.virages[i] > 0 else "bas"))

    coins: dict[tuple[str, float], int] = {}
    for coin in spec.coins:
        coins[(coin.type, coin.taille)] = coins.get((coin.type, coin.taille), 0) + 2

    composants = []
    if spec.composant is not None:
        type_composant, filetage, _, designation_fr, designation_en = COMPOSANTS[spec.composant]
        composants.append(
            Composant(
                designation=spec.t(designation_fr, designation_en),
                type=type_composant,
                filetage=filetage,
                quantite=spec.quantite_composant,
                norme=spec.norme_sertissage,
            )
        )

    return PieceExtraite(
        unites=Champ(valeur="mm"),
        identification=Identification(
            reference=Champ(valeur=spec.reference),
            designation=Champ(valeur=spec.designation),
            indice=Champ(valeur=spec.indice),
        ),
        matiere=Matiere(
            designation=Champ(valeur=spec.matiere),
            famille=Champ(valeur=spec.famille if spec.matiere else None),
            epaisseur=Champ(valeur=spec.epaisseur),
        ),
        encombrement=Encombrement(
            longueur=Champ(valeur=geo.longueur),
            largeur=Champ(valeur=spec.largeur),
            hauteur=Champ(valeur=geo.hauteur),
        ),
        profil_pliage=ProfilPliage(
            cotation="inconnue",
            elements=elements,
            rayon_pliage_general=spec.rayon if spec.rayon_en_note else None,
        ),
        contours=Contours(
            trous=[
                Trou(forme="rond", diametre=g.diametre, quantite=g.quantite, tolerance=g.tolerance)
                for g in spec.trous
            ],
            coins=[
                CoinCoupe(type="chanfrein", cote1=taille, cote2=taille, quantite=quantite)
                if type_coin == "chanfrein"
                else CoinCoupe(type="rayon", rayon=taille, quantite=quantite)
                for (type_coin, taille), quantite in coins.items()
            ],
        ),
        composants=composants,
        traitement=Traitement(
            designation=Champ(valeur=spec.traitement[0] if spec.traitement else None),
            type=Champ(valeur=spec.traitement[1] if spec.traitement else None),
            zones_epargne=[spec.epargne] if spec.epargne else [],
        ),
        tolerance_generale=Champ(valeur=spec.tolerance_generale),
        notes=[Note(texte=n.texte, categorie=n.categorie) for n in spec.notes if n.dans_verite],
        cotes=cotes,
    )
