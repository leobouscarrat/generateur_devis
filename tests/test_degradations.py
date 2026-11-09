"""Tests des dégradations (scan, photo) et de la notation des plans erronés."""

from etude_extraction.comparaison import evaluer_erreur
from etude_extraction.degradations import degrader
from etude_extraction.generateur import generer_piece
from generateur_devis.extraction.documents import charger_plan
from generateur_devis.schema import Anomalie, Champ, PieceExtraite


def test_degradations_reproductibles(tmp_path):
    plan = charger_plan(generer_piece(1, "p0", tmp_path))
    assert plan.texte
    for niveau in (1, 2, 3):
        a, b = degrader(plan, niveau, "p0"), degrader(plan, niveau, "p0")
        assert a.texte == ""  # plus de texte PDF à partir du niveau 1
        assert a.images[0].donnees == b.images[0].donnees
    assert degrader(plan, 2, "p0").images[0].type_mime == "image/jpeg"


def test_notation_erreurs():
    vide = PieceExtraite()
    signale = PieceExtraite(
        anomalies=[
            Anomalie(type="information_manquante", champ="matiere.designation", description="—")
        ]
    )
    invente = PieceExtraite()
    invente.matiere.designation = Champ(valeur="S235", confiance=0.9)
    erreur = {"type": "matiere_absente"}
    assert evaluer_erreur(erreur, vide)[0].statut == "abstention"
    assert evaluer_erreur(erreur, signale)[0].statut == "signale"
    assert evaluer_erreur(erreur, invente)[0].statut == "invente"

    contradiction = {"type": "cotes_contradictoires", "ecart": 5}
    assert evaluer_erreur(contradiction, vide)[1].statut == "non_signale"
    incoherence = PieceExtraite(
        anomalies=[Anomalie(type="incoherence", champ="encombrement", description="112 ≠ 107")]
    )
    assert evaluer_erreur(contradiction, incoherence)[1].champ == "erreur.cotes_contradictoires"
    assert evaluer_erreur(contradiction, incoherence)[1].statut == "signale"


def test_notation_incoherence():
    erreur = {"type": "traitement_incompatible"}
    rien = PieceExtraite(
        anomalies=[Anomalie(type="information_manquante", champ="traitement", description="—")]
    )
    vu = PieceExtraite(
        anomalies=[
            Anomalie(
                type="incoherence", champ="traitement.type", description="anodisation sur acier"
            )
        ]
    )
    assert evaluer_erreur(erreur, rien)[0].statut == "non_signale"  # une absence ne compte pas
    assert evaluer_erreur(erreur, vu)[0].statut == "signale"
