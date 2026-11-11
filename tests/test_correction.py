"""Tests de l'assistant de correction en texte libre (issue #25).

L'appel IA est bouchonné (monkeypatch de ``creer_modele`` dans le module
correction) : les tests portent sur le parsing de la réponse, la validation
contre le schéma et l'application transactionnelle du diff.
"""

from __future__ import annotations

import json

import pytest

from generateur_devis.extraction import correction
from generateur_devis.extraction.correction import (
    DiffCorrection,
    ErreurCorrection,
    PropositionCorrection,
    proposer_correction,
)
from generateur_devis.llm.base import ReponseModele
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
    Trou,
)


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


def _bouchon_modele(monkeypatch, payload: dict | str):
    """Remplace creer_modele par un modèle renvoyant une réponse fixe."""

    class FauxModele:
        nom = "test:correction"

        def generer(self, systeme, message, images):
            texte = payload if isinstance(payload, str) else json.dumps(payload)
            return ReponseModele(texte=texte, modele=self.nom, duree_s=0.0)

    monkeypatch.setattr(correction, "creer_modele", lambda nom: FauxModele())


# --- proposer_correction : parsing et validation de la réponse IA -----------


def test_proposition_remat_ce_qu_elle_comprend(monkeypatch):
    _bouchon_modele(
        monkeypatch,
        {
            "diffs": [
                {
                    "type": "remplacement",
                    "chemin": "matiere.designation.valeur",
                    "nouvelle_valeur": "DC01",
                    "justification": "« inox » lu comme une nuance à préciser",
                }
            ],
            "remarque": "nuance exacte à confirmer",
        },
    )
    proposition = proposer_correction(piece_support(), "c'est de l'inox", "test:correction")
    assert len(proposition.diffs) == 1
    assert proposition.remarque == "nuance exacte à confirmer"


def test_proposition_reponse_non_json_rejetee(monkeypatch):
    _bouchon_modele(monkeypatch, "je ne sais pas quoi répondre")
    with pytest.raises(ErreurCorrection, match="illisible"):
        proposer_correction(piece_support(), "change tout", "test:correction")


def test_proposition_chemin_hors_whitelist_rejete(monkeypatch):
    _bouchon_modele(
        monkeypatch,
        {
            "diffs": [
                {
                    "type": "remplacement",
                    "chemin": "contours.trous",
                    "nouvelle_valeur": [],
                    "justification": "supprimer les trous",
                }
            ]
        },
    )
    with pytest.raises(ErreurCorrection, match="non autorisé"):
        proposer_correction(piece_support(), "enlève les trous", "test:correction")


def test_proposition_texte_vide():
    with pytest.raises(ErreurCorrection, match="Décrivez"):
        proposer_correction(piece_support(), "   ", "test:correction")


# --- PropositionCorrection.appliquer : application transactionnelle ---------


def test_appliquer_remplacement_scalaire():
    piece = piece_support()
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="remplacement",
                chemin="matiere.epaisseur.valeur",
                nouvelle_valeur=3.0,
                justification="épaisseur 3 mm",
            )
        ]
    )
    corrigee = proposition.appliquer(piece)
    assert corrigee.matiere.epaisseur.valeur == 3.0
    assert piece.matiere.epaisseur.valeur == 2.0  # l'originale n'est pas touchée


def test_appliquer_ajout_composant():
    """L'exemple du §4 : « avec 4 écrous M6 »."""
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="ajout_composant",
                nouvelle_valeur={
                    "designation": "Écrou à sertir M6",
                    "type": "ecrou_a_sertir",
                    "filetage": "M6",
                    "quantite": 4,
                },
                justification="4 écrous M6",
            )
        ]
    )
    corrigee = proposition.appliquer(piece_support())
    assert len(corrigee.composants) == 1
    assert corrigee.composants[0].type == "ecrou_a_sertir"
    assert corrigee.composants[0].quantite == 4


def test_appliquer_diff_invalide_annule_tout():
    """Un élément invalide annule TOUT le diff (transactionnel)."""
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="remplacement",
                chemin="matiere.epaisseur.valeur",
                nouvelle_valeur=3.0,
                justification="ok",
            ),
            DiffCorrection(
                type="remplacement",
                chemin="champ.inexistant.valeur",
                nouvelle_valeur=1,
                justification="hors whitelist",
            ),
        ]
    )
    with pytest.raises(ErreurCorrection, match="non autorisé"):
        proposition.appliquer(piece_support())


def test_appliquer_section_absente():
    """Rayon de pliage sur une pièce sans profil → erreur explicite."""
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="remplacement",
                chemin="profil_pliage.rayon_pliage_general",
                nouvelle_valeur=5.0,
                justification="rayon 5",
            )
        ]
    )
    piece = piece_support().model_copy(update={"profil_pliage": None})
    with pytest.raises(ErreurCorrection, match="section absente"):
        proposition.appliquer(piece)


def test_appliquer_composant_invalide():
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="ajout_composant",
                nouvelle_valeur={"designation": "???", "type": "soudure", "quantite": 0},
                justification="invalide",
            )
        ]
    )
    with pytest.raises(ErreurCorrection, match="Composant invalide"):
        proposition.appliquer(piece_support())


def test_ligne_avant_apres():
    piece = piece_support()
    proposition = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="remplacement",
                chemin="matiere.epaisseur.valeur",
                nouvelle_valeur=3.0,
                justification="3 mm",
            )
        ]
    )
    lignes = proposition.ligne_avant_apres(piece)
    assert lignes == [("matiere.epaisseur.valeur", "2.0", "3.0", "3 mm")]
