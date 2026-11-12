"""Tests de la conversion des plans en pouces vers le mm (issue #57).

Valeurs attendues calculées à la main (1 in = 25,4 mm) et écrites en dur.
"""

from __future__ import annotations

import types
import typing

import pytest
from pydantic import BaseModel

from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Contours,
    Cote,
    Encombrement,
    EtatSurface,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Soudure,
    Source,
    ToleranceGeometrique,
    Trou,
    Unite,
)
from generateur_devis.unites import (
    LONGUEURS,
    MM_PAR_POUCE,
    NON_LONGUEURS,
    ConversionUnites,
    ValeurConvertie,
    convertir_en_mm,
    message_unites,
    valeur_origine,
)


def piece_pouces(unite: Unite | None = "in") -> PieceExtraite:
    """Pièce qui renseigne chaque champ de LONGUEURS (valeurs en pouces)."""
    return PieceExtraite(
        unites=Champ[Unite](valeur=unite, confiance=0.9),
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"),
            epaisseur=Champ[float](
                valeur=0.06, confiance=0.8, source=Source(page=2, zone=(0.1, 0.2, 0.3, 0.4))
            ),
        ),
        encombrement=Encombrement(
            longueur=Champ[float](valeur=4.0),
            largeur=Champ[float](valeur=1.75),
            hauteur=Champ[float](valeur=0.5),
        ),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=0.03,
            elements=[
                Aile(longueur=1.0),
                Pli(angle=90.0, sens="haut", rayon_interieur=0.06),
                Aile(longueur=0.5),
            ],
        ),
        contours=Contours(
            trous=[
                Trou(forme="rond", diametre=0.75, quantite=2, tolerance="+0.005/-0"),
                Trou(forme="oblong", longueur=0.5, largeur=0.25),
            ],
            coins=[
                CoinCoupe(type="chanfrein", cote1=0.25, cote2=0.125, quantite=2),
                CoinCoupe(type="rayon", rayon=0.125),
            ],
            autres_decoupes=["encoche 0.5 x 0.25"],
        ),
        soudures=[Soudure(longueur=2.0, gorge=0.125, quantite=3, texte="a0.125")],
        cotes=[
            Cote(valeur=1.75, type="lineaire", quantite=2, texte="2X 1.75"),
            Cote(valeur=90.0, type="angle", texte="90°"),
        ],
        tolerances_geometriques=[
            ToleranceGeometrique(type="position", valeur=0.005, quantite=4, texte="⌖ 0.005 A B")
        ],
        etats_surface=[EtatSurface(valeur=63.0, texte="63 RMS")],
    )


ATTENDU_MM = {
    "matiere.epaisseur.valeur": (0.06, 1.524),
    "encombrement.longueur.valeur": (4.0, 101.6),
    "encombrement.largeur.valeur": (1.75, 44.45),
    "encombrement.hauteur.valeur": (0.5, 12.7),
    "profil_pliage.elements[0].longueur": (1.0, 25.4),
    "profil_pliage.elements[1].rayon_interieur": (0.06, 1.524),
    "profil_pliage.elements[2].longueur": (0.5, 12.7),
    "profil_pliage.rayon_pliage_general": (0.03, 0.762),
    "contours.trous[0].diametre": (0.75, 19.05),
    "contours.trous[1].longueur": (0.5, 12.7),
    "contours.trous[1].largeur": (0.25, 6.35),
    "contours.coins[0].cote1": (0.25, 6.35),
    "contours.coins[0].cote2": (0.125, 3.175),
    "contours.coins[1].rayon": (0.125, 3.175),
    "soudures[0].longueur": (2.0, 50.8),
    "soudures[0].gorge": (0.125, 3.175),
    "tolerances_geometriques[0].valeur": (0.005, 0.127),
    "cotes[0].valeur": (1.75, 44.45),
}


# --- Conversion des longueurs ------------------------------------------------


def test_mm_par_pouce_definition_exacte():
    assert MM_PAR_POUCE == 25.4


def test_convertit_toutes_les_longueurs():
    sortie, _ = convertir_en_mm(piece_pouces())
    assert sortie.unites.valeur == "mm"
    assert sortie.matiere.epaisseur.valeur == pytest.approx(1.524)
    assert sortie.encombrement.longueur.valeur == pytest.approx(101.6)
    assert sortie.encombrement.largeur.valeur == pytest.approx(44.45)
    assert sortie.encombrement.hauteur.valeur == pytest.approx(12.7)
    profil = sortie.profil_pliage
    assert profil is not None
    assert profil.rayon_pliage_general == pytest.approx(0.762)
    aile0, pli, aile2 = profil.elements
    assert isinstance(aile0, Aile) and isinstance(pli, Pli) and isinstance(aile2, Aile)
    assert aile0.longueur == pytest.approx(25.4)
    assert pli.rayon_interieur == pytest.approx(1.524)
    assert aile2.longueur == pytest.approx(12.7)
    rond, oblong = sortie.contours.trous
    assert rond.diametre == pytest.approx(19.05)
    assert (oblong.longueur, oblong.largeur) == (pytest.approx(12.7), pytest.approx(6.35))
    chanfrein, coin_rayon = sortie.contours.coins
    assert (chanfrein.cote1, chanfrein.cote2) == (pytest.approx(6.35), pytest.approx(3.175))
    assert coin_rayon.rayon == pytest.approx(3.175)
    assert sortie.soudures[0].longueur == pytest.approx(50.8)
    assert sortie.soudures[0].gorge == pytest.approx(3.175)
    assert sortie.cotes[0].valeur == pytest.approx(44.45)
    assert sortie.tolerances_geometriques[0].valeur == pytest.approx(0.127)


def test_ne_convertit_ni_angles_ni_quantites_ni_rugosites_ni_textes():
    sortie, _ = convertir_en_mm(piece_pouces())
    pli = sortie.profil_pliage.elements[1]
    assert isinstance(pli, Pli)
    assert pli.angle == 90.0
    assert sortie.cotes[1].valeur == 90.0  # cote d'angle
    assert sortie.contours.trous[0].quantite == 2
    assert sortie.contours.coins[0].quantite == 2
    assert sortie.soudures[0].quantite == 3
    assert sortie.cotes[0].quantite == 2
    assert sortie.tolerances_geometriques[0].quantite == 4
    assert sortie.etats_surface[0].valeur == 63.0
    assert sortie.contours.trous[0].tolerance == "+0.005/-0"
    assert sortie.contours.autres_decoupes == ["encoche 0.5 x 0.25"]
    assert sortie.soudures[0].texte == "a0.125"
    assert sortie.cotes[0].texte == "2X 1.75"


def test_confiance_et_source_conservees():
    sortie, _ = convertir_en_mm(piece_pouces())
    assert sortie.matiere.epaisseur.confiance == 0.8
    assert sortie.matiere.epaisseur.source == Source(page=2, zone=(0.1, 0.2, 0.3, 0.4))
    assert sortie.unites.confiance == 0.9


def test_piece_entree_non_modifiee():
    entree = piece_pouces()
    copie = entree.model_copy(deep=True)
    convertir_en_mm(entree)
    assert entree == copie
    assert entree.matiere.epaisseur.valeur == 0.06
    assert entree.unites.valeur == "in"


def test_champs_none_restent_none_sans_trace():
    sortie, conversion = convertir_en_mm(piece_pouces())
    rond, oblong = sortie.contours.trous
    assert (rond.longueur, rond.largeur) == (None, None)
    assert oblong.diametre is None
    chemins = {v.chemin for v in conversion.valeurs}
    assert "contours.trous[0].longueur" not in chemins
    assert "contours.trous[1].diametre" not in chemins


def test_profil_pliage_null_sans_erreur():
    entree = PieceExtraite(
        unites=Champ[Unite](valeur="in"),
        matiere=Matiere(epaisseur=Champ[float](valeur=0.13)),
    )
    sortie, conversion = convertir_en_mm(entree)
    assert sortie.profil_pliage is None
    assert sortie.matiere.epaisseur.valeur == pytest.approx(3.302)
    assert [v.chemin for v in conversion.valeurs] == ["matiere.epaisseur.valeur"]


# --- Trace -------------------------------------------------------------------


def test_trace_chaque_valeur_convertie():
    _, conversion = convertir_en_mm(piece_pouces())
    assert conversion.unite_origine == "in"
    traces = {v.chemin: v for v in conversion.valeurs}
    assert set(traces) == set(ATTENDU_MM)
    assert len(conversion.valeurs) == 18
    for chemin, (origine, mm) in ATTENDU_MM.items():
        assert traces[chemin].valeur_origine == origine, chemin
        assert traces[chemin].valeur_mm == pytest.approx(mm), chemin


def test_trace_epaisseur_umaine():
    _, conversion = convertir_en_mm(piece_pouces())
    trace = next(v for v in conversion.valeurs if v.chemin == "matiere.epaisseur.valeur")
    assert trace.valeur_origine == 0.06
    assert trace.valeur_mm == pytest.approx(1.524)


# --- Unité mm / non lue / idempotence -----------------------------------------


def test_piece_en_mm_inchangee():
    entree = piece_pouces("mm")
    sortie, conversion = convertir_en_mm(entree)
    assert sortie == entree
    assert sortie is not entree
    assert conversion == ConversionUnites(unite_origine="mm", valeurs=[])


def test_unite_non_lue_rien_converti():
    entree = piece_pouces(None)
    sortie, conversion = convertir_en_mm(entree)
    assert sortie == entree
    assert sortie.matiere.epaisseur.valeur == 0.06
    assert conversion.unite_origine is None
    assert conversion.valeurs == []


def test_idempotence():
    une_fois, _ = convertir_en_mm(piece_pouces())
    deux_fois, conversion = convertir_en_mm(une_fois)
    assert deux_fois == une_fois
    assert conversion.unite_origine == "mm"
    assert conversion.valeurs == []


# --- valeur_origine / message_unites ------------------------------------------


def _conversion_umaine() -> ConversionUnites:
    return ConversionUnites(
        unite_origine="in",
        valeurs=[
            ValeurConvertie(chemin="matiere.epaisseur.valeur", valeur_origine=0.06, valeur_mm=1.524)
        ],
    )


def test_valeur_origine_valeur_intacte():
    assert valeur_origine(_conversion_umaine(), "matiere.epaisseur.valeur", 1.524) == 0.06


def test_valeur_origine_valeur_modifiee_apres_conversion():
    assert valeur_origine(_conversion_umaine(), "matiere.epaisseur.valeur", 1.5) is None


def test_valeur_origine_chemin_non_converti_ou_sans_conversion():
    assert valeur_origine(_conversion_umaine(), "encombrement.largeur.valeur", 1.524) is None
    assert valeur_origine(None, "matiere.epaisseur.valeur", 1.524) is None
    assert valeur_origine(_conversion_umaine(), "matiere.epaisseur.valeur", None) is None


def test_valeur_origine_sur_sortie_reelle():
    sortie, conversion = convertir_en_mm(piece_pouces())
    epaisseur_mm = sortie.matiere.epaisseur.valeur
    assert valeur_origine(conversion, "matiere.epaisseur.valeur", epaisseur_mm) == 0.06


def test_message_unites_pouces():
    _, conversion = convertir_en_mm(piece_pouces())
    assert message_unites(conversion) == (
        "info",
        "Plan coté en pouces : 18 valeurs converties en mm (× 25,4) par le code.",
    )


def test_message_unites_pouces_une_seule_valeur():
    assert message_unites(_conversion_umaine()) == (
        "info",
        "Plan coté en pouces : 1 valeur convertie en mm (× 25,4) par le code.",
    )


def test_message_unites_mm():
    assert message_unites(ConversionUnites(unite_origine="mm")) == ("info", "Plan coté en mm.")


def test_message_unites_non_lue():
    assert message_unites(ConversionUnites(unite_origine=None)) == (
        "alerte",
        "Unité non lue sur le plan : les cotes sont prises en mm, à vérifier.",
    )


# --- Garde-fou dérivé du schéma -------------------------------------------------


def _est_champ(annotation) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, Champ)


def _est_flottant(annotation) -> bool:
    """float, float | None ou Champ[float]."""
    if annotation is float:
        return True
    if _est_champ(annotation):
        return annotation.__pydantic_generic_metadata__["args"] == (float,)
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        args = set(typing.get_args(annotation))
        return float in args and args <= {float, type(None)}
    return False


def _modeles_contenus(annotation) -> list[type[BaseModel]]:
    """Modèles du schéma atteignables depuis une annotation (listes, unions, Annotated)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [] if _est_champ(annotation) else [annotation]
    modeles = []
    for arg in typing.get_args(annotation):
        modeles += _modeles_contenus(arg)
    return modeles


def _champs_flottants_du_schema() -> set[tuple[type[BaseModel], str]]:
    trouves: set[tuple[type[BaseModel], str]] = set()
    a_visiter: list[type[BaseModel]] = [PieceExtraite]
    vus: set[type[BaseModel]] = set()
    while a_visiter:
        modele = a_visiter.pop()
        if modele in vus:
            continue
        vus.add(modele)
        for nom, info in modele.model_fields.items():
            if nom == "confiance":
                continue
            if _est_flottant(info.annotation):
                trouves.add((modele, nom))
            a_visiter += _modeles_contenus(info.annotation)
    return trouves


def test_garde_fou_tout_champ_flottant_est_classe():
    """Toute extension du schéma force un classement longueur / non-longueur explicite."""
    longueurs = {(m, c) for m, champs in LONGUEURS.items() for c in champs}
    non_longueurs = {(m, c) for m, champs in NON_LONGUEURS.items() for c in champs}
    assert not longueurs & non_longueurs
    du_schema = _champs_flottants_du_schema()
    # Le parcours trouve bien des champs (le test ne passe pas à vide).
    assert (Matiere, "epaisseur") in du_schema
    assert (Pli, "angle") in du_schema
    assert du_schema == longueurs | non_longueurs
