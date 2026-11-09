"""Tests du générateur de plans de tôlerie."""

import json
import random

import pymupdf

from etude_extraction.comparaison import comparer
from etude_extraction.generateur import generer_piece
from etude_extraction.generateur.modele import FORMES, geometrie, tirer_piece
from generateur_devis.schema import PieceExtraite


def test_tirage_reproductible():
    a, _ = tirer_piece(random.Random("graine-1"), "p")
    b, _ = tirer_piece(random.Random("graine-1"), "p")
    assert a == b


def test_toutes_les_formes_sont_tirees():
    formes = {tirer_piece(random.Random(f"g-{i}"), "p")[0].forme for i in range(80)}
    assert formes == set(FORMES)


def test_geometrie_z():
    spec, _ = tirer_piece(random.Random("g-0"), "p")
    spec.forme, spec.cap, spec.virages, spec.ailes, spec.epaisseur = (
        "Z",
        0,
        [1, -1],
        [18, 22, 42],
        2,
    )
    geo = geometrie(spec)
    assert geo.longueur == 60 and geo.hauteur == 24
    assert [geo.horizontale(i) for i in range(3)] == [True, False, True]


def test_plan_et_bonne_reponse(tmp_path):
    for i in range(5):
        pdf = generer_piece(1, f"p{i}", tmp_path)
        verite = PieceExtraite.model_validate_json(pdf.with_suffix(".json").read_text())
        assert verite.problemes_coherence() == []
        assert verite.cotes, "le plan doit contenir des cotes"
        with pymupdf.open(pdf) as document:
            texte = document[0].get_text()
        # Les informations du cartouche sont bien imprimées sur le plan.
        assert verite.identification.reference.valeur in texte
        if verite.matiere.designation.valeur:
            assert verite.matiere.designation.valeur in texte
        # Une extraction parfaite obtient un score parfait.
        resultats = comparer(verite, verite)
        assert all(r.statut in ("juste", "absent_ok", "liste") for r in resultats)
        assert all(r.apparies == r.attendus for r in resultats if r.statut == "liste")


def test_plans_errones(tmp_path):
    from etude_extraction.generateur.modele import ERREURS

    for i, type_erreur in enumerate(ERREURS):
        pdf = generer_piece(7, f"e{i}", tmp_path, type_erreur)
        verite = PieceExtraite.model_validate_json(pdf.with_suffix(".json").read_text())
        texte = pymupdf.open(pdf)[0].get_text()
        if type_erreur == "epaisseur_absente":
            assert verite.matiere.epaisseur.valeur is None
        if type_erreur == "matiere_absente":
            assert verite.matiere.designation.valeur is None
        if type_erreur in ("cote_aile_absente", "cotes_contradictoires"):
            assert len(verite.profil_pliage.elements) >= 3  # au moins un pli
        assert texte


def test_plans_incoherents(tmp_path):
    from etude_extraction.generateur.modele import INCOHERENCES

    for i, type_erreur in enumerate(INCOHERENCES):
        pdf = generer_piece(9, f"i{i}", tmp_path, type_erreur)
        texte = pymupdf.open(pdf)[0].get_text()
        erreur = json.loads(pdf.with_suffix(".erreur.json").read_text())
        if type_erreur == "quantite_trous_incoherente":
            assert f"{erreur['annoncee']}x" in texte
        if type_erreur == "traitement_incompatible":
            assert erreur["traitement"] in ("anodisation", "galvanisation")
