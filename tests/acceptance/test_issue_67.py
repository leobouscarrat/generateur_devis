"""Acceptance #67 : l'avant/après de l'assistant de correction est lisible.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
est déposée dans ``session_state`` (``CLE_RESULTAT``, ``CLE_CONTEXTE``) avec une
proposition de correction déjà prête (``CLE_PROPOSITION``) — aucun appel IA.
Le tableau avant/après doit afficher des libellés métier et seulement la
valeur qui change, sans ``confiance``/``source`` ni chemin technique.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.extraction.correction import DiffCorrection, PropositionCorrection
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Composant,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Source,
)
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_PROPOSITION, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis

ECROUS = "CRIMPING NUTS M6 1,00 CL8 S2S"


def piece_avec_ecrous() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=2.0,
            elements=[Aile(longueur=42.0), Pli(angle=90.0, sens="haut"), Aile(longueur=22.0)],
        ),
        composants=[
            Composant(
                designation=ECROUS,
                type="ecrou_a_sertir",
                filetage="M6",
                quantite=2,
                confiance=0.9,
                source=Source(page=1, zone=(0.1, 0.2, 0.3, 0.4)),
            )
        ],
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def test_avant_apres_lisible_pour_une_modification_de_composant():
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_avec_ecrous(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    at.session_state[CLE_PROPOSITION] = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="modification_element",
                chemin="composants[0]",
                nouvelle_valeur={"quantite": 4},
                justification="4 écrous",
            )
        ]
    )
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    tableaux = [t.value for t in at.table if "Justification" in t.value.columns]
    assert len(tableaux) == 1  # le tableau avant/après de l'assistant
    tableau = tableaux[0]
    lignes = [tuple(str(v) for v in ligne) for ligne in tableau.itertuples(index=False)]
    assert lignes == [(f"Composant « {ECROUS} » : Quantité", "2", "4", "4 écrous")]
    cellules = [c for ligne in lignes for c in ligne]
    for interdit in ("confiance", "source", "composants[0]", "{"):
        assert not any(interdit in c for c in cellules), interdit
    # Diff applicable : le bouton Accepter est actif.
    accepter = next(b for b in at.button if b.label == "✅ Accepter")
    assert not accepter.disabled
