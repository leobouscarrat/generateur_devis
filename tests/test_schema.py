import json
from pathlib import Path

import pytest

from generateur_devis.schema import Aile, PieceExtraite, Pli, ProfilPliage
from generateur_devis.schema.export import CHEMIN_SCHEMA, texte_schema

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / "exemples" / "equerre_fictive.json"
PIECE_003 = RACINE / "data" / "prive" / "annotations" / "piece_003.json"


def charger(chemin: Path) -> PieceExtraite:
    return PieceExtraite.model_validate_json(chemin.read_text(encoding="utf-8"))


def test_exemple_fictif_valide():
    piece = charger(EXEMPLE)
    assert piece.matiere.epaisseur.valeur == 2.0
    assert piece.profil_pliage is not None and piece.profil_pliage.nb_plis == 1
    assert piece.problemes_coherence() == []


@pytest.mark.skipif(not PIECE_003.exists(), reason="annotation privée absente")
def test_annotation_piece_003_valide():
    piece = charger(PIECE_003)
    assert piece.profil_pliage is not None and piece.profil_pliage.nb_plis == 2
    assert piece.matiere.designation.valeur is None  # matière absente du plan
    assert sum(c.quantite for c in piece.composants) == 2
    assert piece.problemes_coherence() == []


def test_aller_retour_json():
    piece = charger(EXEMPLE)
    assert PieceExtraite.model_validate_json(piece.model_dump_json()) == piece


def test_piece_vide_valide():
    """Une réponse où rien n'a pu être lu reste valide : tout vaut null."""
    piece = PieceExtraite()
    assert piece.matiere.designation.valeur is None
    assert piece.problemes_coherence() == []


def test_champ_inconnu_refuse():
    donnees = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    donnees["champ_invente"] = 1
    with pytest.raises(ValueError):
        PieceExtraite.model_validate(donnees)


def test_profil_incoherent_signale():
    piece = PieceExtraite(
        profil_pliage=ProfilPliage(elements=[Aile(longueur=10), Aile(longueur=20), Pli(angle=90)])
    )
    problemes = piece.problemes_coherence()
    assert any("élément 1" in p for p in problemes)
    assert any("finir par une aile" in p for p in problemes)


def test_schema_exporte_a_jour():
    """Le fichier versionné doit correspondre au code : relancer l'export sinon."""
    assert CHEMIN_SCHEMA.read_text(encoding="utf-8") == texte_schema()
