"""Acceptance #57 : un plan coté en pouces est converti en mm par le code, tracé.

1. Pipeline (fonction pure, base seedée en mémoire, extraction bouchonnée) :
   la conversion a lieu après l'extraction, avant géométrie / faisabilité /
   chiffrage, sans arrondi vers le stock.
2. Écran de validation (``streamlit.testing.v1.AppTest``, base locale seedée) :
   unité d'origine, liste des valeurs converties, « lu sur le plan : 0,06 in →
   1,52 mm » sous les champs, alerte « unité non lue » même formulaire bloqué.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.extraction import ResultatExtraction
from generateur_devis.extraction.prompt import VERSION_PROMPT
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
    Unite,
)
from generateur_devis.ui import pipeline
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis, orchestrer_devis
from generateur_devis.unites import convertir_en_mm


def piece_umaine(unite: Unite | None = "in", confiance_unite: float | None = None) -> PieceExtraite:
    """Support coté en pouces : épaisseur 0,06 in, largeur 2,36 in, R 0,08 in."""
    return PieceExtraite(
        unites=Champ[Unite](valeur=unite, confiance=confiance_unite),
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=0.06)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=2.36)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=0.08,
            elements=[
                Aile(longueur=1.65),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=0.87),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=0.71),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=0.75, quantite=2)]),
    )


# --- 1. Pipeline ----------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed(session)
    yield session
    session.close()


def _bouchon(monkeypatch, piece: PieceExtraite) -> list[PieceExtraite]:
    """Bouchonne l'IA ; renvoie la liste des pièces vues par la faisabilité."""
    monkeypatch.setattr(pipeline, "charger_plan", lambda chemin: object())
    monkeypatch.setattr(
        pipeline,
        "extraire",
        lambda document, modele, **kw: ResultatExtraction("test:m", "test", piece, None),
    )
    monkeypatch.setattr(pipeline, "creer_modele", lambda nom: object())
    vues: list[PieceExtraite] = []
    vraie_faisabilite = pipeline.evaluer_faisabilite

    def espion(piece_vue, matiere_id, session):
        vues.append(piece_vue)
        return vraie_faisabilite(piece_vue, matiere_id, session)

    monkeypatch.setattr(pipeline, "evaluer_faisabilite", espion)
    return vues


def test_pipeline_convertit_apres_extraction_et_trace(monkeypatch, session):
    brute = piece_umaine()
    vues = _bouchon(monkeypatch, brute)
    resultat = orchestrer_devis(b"%PDF", "umaine.pdf", None, None, None, "test:m", session)

    # La faisabilité a reçu la pièce en mm (0,06 in = 1,524 mm, 0,75 in = 19,05 mm).
    assert len(vues) == 1
    assert vues[0].unites.valeur == "mm"
    assert vues[0].matiere.epaisseur.valeur == pytest.approx(1.524)
    assert vues[0].contours.trous[0].diametre == pytest.approx(19.05)
    # La sortie brute de l'extraction n'est pas modifiée (évaluation inchangée).
    assert brute.unites.valeur == "in"
    assert brute.matiere.epaisseur.valeur == 0.06
    # Trace : chemin, valeur en pouces, valeur en mm.
    traces = {v.chemin: (v.valeur_origine, v.valeur_mm) for v in resultat.conversion.valeurs}
    assert traces["matiere.epaisseur.valeur"] == (0.06, pytest.approx(1.524))
    assert traces["profil_pliage.elements[2].longueur"] == (0.87, pytest.approx(22.098))
    # Pas d'arrondi vers 1,5 : la faisabilité bloque, pas de chiffrage, pas d'exception.
    assert resultat.piece.matiere.epaisseur.valeur != 1.5
    assert any(c.regle == "epaisseur_dispo" for c in resultat.constats)
    assert resultat.chiffrage is None


def test_extraction_et_prompt_non_touches():
    """Conversion absente de extraire() (l'évaluation compare la sortie brute) et
    CONSIGNES inchangées : VERSION_PROMPT reste celle d'avant #57 (cache valide)."""
    import inspect

    from generateur_devis.extraction import extracteur

    assert "convertir_en_mm" not in inspect.getsource(extracteur)
    assert "unites" not in inspect.getsource(extracteur.extraire)
    assert VERSION_PROMPT == "v4"  # v3 sous #57, bump par la règle 14 de #64


# --- 2. Écran de validation --------------------------------------------------------


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer(resultat: ResultatDevis) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = resultat
    at.session_state[CLE_CONTEXTE] = {"client_id": None, "quantites": [1, 100], "nom_modele": "t"}
    return at.run()


def _resultat_converti(**kwargs) -> ResultatDevis:
    piece, conversion = convertir_en_mm(piece_umaine(**kwargs))
    return ResultatDevis(piece=piece, matiere_id="S235JR", conversion=conversion)


def test_ecran_plan_en_pouces_unite_et_valeurs_converties():
    at = _lancer(_resultat_converti())
    assert not at.exception, [e.value for e in at.exception]

    infos = [i.value for i in at.info]
    assert "Plan coté en pouces : 7 valeurs converties en mm (× 25,4) par le code." in infos
    expander = next(e for e in at.expander if e.label == "Valeurs converties")
    liste = " ".join(m.value for m in expander.markdown)
    assert "matiere.epaisseur.valeur : 0,06 in → 1,52 mm" in liste
    assert "contours.trous[0].diametre : 0,75 in → 19,05 mm" in liste

    epaisseur = next(n for n in at.number_input if n.label == "Épaisseur (mm)")
    assert epaisseur.value == pytest.approx(1.524)  # stockage exact, pas d'arrondi
    captions = [c.value for c in at.caption]
    assert "Épaisseur (mm) : lu sur le plan : 0,06 in → 1,52 mm." in captions
    assert "Largeur d'encombrement (mm) : lu sur le plan : 2,36 in → 59,94 mm." in captions
    assert "Rayon de pliage général (mm) : lu sur le plan : 0,08 in → 2,03 mm." in captions

    # 1,524 mm n'est pas au stock : signalé par la faisabilité, jamais corrigé.
    # Message formaté (:g) : pas de bruit flottant « 1.5239999999999998 ».
    assert any("Épaisseur 1.524 mm non disponible" in e.value for e in at.error)


def test_ecran_valeur_modifiee_apres_conversion_plus_en_pouces():
    resultat = _resultat_converti()
    resultat.piece.matiere.epaisseur.valeur = 1.5  # ex. corrigée par l'assistant
    at = _lancer(resultat)
    captions = [c.value for c in at.caption]
    assert "Épaisseur (mm) : lu sur le plan." in captions
    assert not [c for c in captions if c.startswith("Épaisseur (mm)") and " in " in c]


def test_ecran_unite_non_lue_alerte_meme_formulaire_bloque():
    piece, conversion = convertir_en_mm(piece_umaine(unite=None))
    piece.matiere.epaisseur.valeur = None  # formulaire bloqué (épaisseur à saisir)
    at = _lancer(ResultatDevis(piece=piece, matiere_id="S235JR", conversion=conversion))
    assert not at.exception, [e.value for e in at.exception]

    # Streamlit extrait l'emoji de tête (⚠️) en icône : .value ne le contient pas.
    assert "Unité non lue sur le plan : les cotes sont prises en mm, à vérifier." in [
        w.value for w in at.warning
    ]
    assert not [b for b in at.button if b.label == "Valider la pièce"]  # bloqué
    assert not [e for e in at.expander if e.label == "Valeurs converties"]


def test_ecran_unite_lue_avec_faible_confiance():
    at = _lancer(_resultat_converti(confiance_unite=0.4))
    assert "Lecture incertaine — unité du plan : confiance 40%" in [w.value for w in at.warning]
