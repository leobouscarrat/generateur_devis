"""Tests de la ventilation des coûts pour l'écran de validation.

Le chiffrage est réel (base SQLite en mémoire seedée) : on vérifie que la
ventilation et la trace reprennent exactement les montants du ``Chiffrage``.
"""

from __future__ import annotations

import pytest

from generateur_devis.calcul_prix import chiffrer
from generateur_devis.data.db import get_session
from generateur_devis.data.seed import seed
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    CoinCoupe,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Traitement,
    Trou,
    TypeTraitement,
)
from generateur_devis.ui.ventilation import lignes_trace, ventilation_couts

MATIERE = "S235JR"


def piece_support() -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures."""
    return PieceExtraite(
        matiere=Matiere(epaisseur=Champ[float](valeur=2.0)),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
        contours=Contours(
            trous=[Trou(forme="rond", diametre=8.75, quantite=2)],
            coins=[CoinCoupe(type="chanfrein", cote1=20.0, quantite=2)],
        ),
    )


@pytest.fixture
def session():
    with get_session() as session:
        seed(session)
        session.commit()
        yield session
        session.rollback()


def test_ventilation_reprend_les_blocs(session):
    """Chaque ligne de ventilation reprend les montants exacts du bloc."""
    chiffrage = chiffrer(piece_support(), MATIERE, session, composants=[("ES-M6-A", 2)])
    lignes = ventilation_couts(chiffrage)
    par_bloc = {lig["bloc"]: lig for lig in lignes}

    assert par_bloc["Matière"]["variable_eur_piece"] == pytest.approx(
        chiffrage.blocs_1_3.matiere.cout_variable_eur
    )
    assert par_bloc["Découpe"]["fixe_eur_lot"] == pytest.approx(
        chiffrage.blocs_1_3.decoupe.cout_fixe_eur_par_lot
    )
    assert par_bloc["Pliage"]["variable_eur_piece"] == pytest.approx(
        chiffrage.blocs_1_3.pliage.cout_variable_eur
    )
    assert "Composants & opérations" in par_bloc
    # Pas de finition demandée → pas de ligne Finition ; soudure à 0 → absente.
    assert "Finition" not in par_bloc
    assert "Soudure" not in par_bloc


def test_ventilation_detail_lisible(session):
    """Le détail explique l'origine (prix matière, taux horaire, nb de plis)."""
    chiffrage = chiffrer(piece_support(), MATIERE, session)
    par_bloc = {lig["bloc"]: lig for lig in ventilation_couts(chiffrage)}
    assert "€/kg" in par_bloc["Matière"]["detail"]
    assert "calepinage" in par_bloc["Matière"]["detail"]
    assert "€/h" in par_bloc["Découpe"]["detail"]
    assert "2 pli(s)" in par_bloc["Pliage"]["detail"]


def test_ventilation_avec_finition(session):
    """Une pièce avec traitement ajoute la ligne Finition (minimum de lot)."""
    piece = piece_support().model_copy(
        update={"traitement": Traitement(type=Champ[TypeTraitement](valeur="thermolaquage"))}
    )
    chiffrage = chiffrer(piece, MATIERE, session)
    par_bloc = {lig["bloc"]: lig for lig in ventilation_couts(chiffrage)}
    assert "Finition" in par_bloc
    assert "minimum de lot" in par_bloc["Finition"]["detail"]


def test_trace_complete_et_figee(session):
    """La trace couvre tous les blocs et porte l'origine des données."""
    chiffrage = chiffrer(piece_support(), MATIERE, session)
    lignes = lignes_trace(chiffrage)
    blocs = {lig["bloc"] for lig in lignes}
    assert {"matiere", "decoupe", "pliage"} <= blocs
    for ligne in lignes:
        assert ligne["formule"]
        assert ligne["origine"]
    # Le prix matière porte sa date de mise à jour (traçabilité des prix).
    assert any(lig["bloc"] == "matiere" and lig["date_prix"] != "—" for lig in lignes)
