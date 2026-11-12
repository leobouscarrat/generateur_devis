"""Acceptance #84 : un diff mal formé de l'assistant ne fait plus planter l'écran.

``streamlit.testing.v1.AppTest`` : la pièce (sans profil de pliage) est déposée
dans ``session_state`` ; la proposition est soit déjà prête
(``CLE_PROPOSITION``), soit produite par un modèle bouchonné (aucun appel IA).
"""

from __future__ import annotations

import json

from streamlit.testing.v1 import AppTest

from generateur_devis.extraction import correction
from generateur_devis.extraction.correction import DiffCorrection, PropositionCorrection
from generateur_devis.llm.base import ReponseModele
from generateur_devis.schema.piece import Champ, Encombrement, Matiere, PieceExtraite
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_PROPOSITION, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis


def piece_sans_profil() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _app_test(proposition: PropositionCorrection | None = None) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_sans_profil(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    if proposition is not None:
        at.session_state[CLE_PROPOSITION] = proposition
    return at


def _verifier_refus(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    erreurs = [e.value for e in at.error]
    assert any("Correction inapplicable" in e for e in erreurs), erreurs
    accepter = next(b for b in at.button if b.label == "✅ Accepter")
    assert accepter.disabled


def test_element_de_profil_absent_n_fait_pas_planter_l_ecran():
    at = _app_test(
        PropositionCorrection(
            diffs=[
                DiffCorrection(
                    type="modification_element",
                    chemin="profil_pliage.elements[0]",
                    nouvelle_valeur={"sens": "haut"},
                    justification="pli vers le haut",
                )
            ]
        )
    )
    at.run()
    _verifier_refus(at)
    assert any("section absente" in e.value for e in at.error)


def test_designation_non_scalaire_refusee():
    at = _app_test(
        PropositionCorrection(
            diffs=[
                DiffCorrection(
                    type="remplacement",
                    chemin="matiere.designation.valeur",
                    nouvelle_valeur={"nuance": "DC01"},
                    justification="DC01",
                )
            ]
        )
    )
    at.run()
    _verifier_refus(at)
    assert any("attendu : un texte" in e.value for e in at.error)


def test_proposition_mal_formee_rejetee_avant_affichage(monkeypatch):
    class FauxModele:
        nom = "test:correction"

        def generer(self, systeme, message, images):
            texte = json.dumps(
                {
                    "diffs": [
                        {
                            "type": "modification_element",
                            "chemin": "profil_pliage.elements[1]",
                            "nouvelle_valeur": {"sens": "haut"},
                            "justification": "pli vers le haut",
                        }
                    ]
                }
            )
            return ReponseModele(texte=texte, modele=self.nom, duree_s=0.0)

    monkeypatch.setattr(correction, "creer_modele", lambda nom: FauxModele())
    at = _app_test()
    at.run()
    at.text_area(key="texte_correction").input("le pli monte").run()
    next(b for b in at.button if b.label == "Proposer une correction").click()
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    erreurs = [e.value for e in at.error]
    assert any("L'assistant propose une correction inapplicable" in e for e in erreurs), erreurs
    assert CLE_PROPOSITION not in at.session_state
