"""Acceptance #56 : les composants extraits sont rattachés au référentiel et chiffrés.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
(SUPPORT du §8 + composants) est déposée dans ``session_state`` comme le fait
l'écran de dépôt, puis ``main()`` route vers l'écran de validation. La base
locale seedée (``data/devis.db``, via ``get_session``) est lue, jamais écrite.

``st.data_editor`` n'est pas pilotable par AppTest : le choix manuel d'une
référence est couvert par ``lire_composants`` (tests/test_validation.py) ; ici
on vérifie les deux chemins sans saisie — candidat unique pré-sélectionné
(chiffré) et plusieurs candidats (⚠️ non chiffré, non bloquant).
"""

from __future__ import annotations

import json

from streamlit.proto.WidgetStates_pb2 import WidgetState, WidgetStates
from streamlit.testing.v1 import AppTest

from generateur_devis.extraction.correction import DiffCorrection, PropositionCorrection
from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Composant,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
)
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_PROPOSITION, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis

BLOC_COMPOSANTS = "Composants & opérations"


def piece_support(filetage: str) -> PieceExtraite:
    """SUPPORT du §8 (Z, 2 plis 90°, S235JR 2 mm) avec 2 écrous à sertir."""
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
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
        contours=Contours(trous=[Trou(forme="rond", diametre=8.75, quantite=2)]),
        composants=[
            Composant(
                designation=f"Écrou à sertir {filetage}",
                type="ecrou_a_sertir",
                filetage=filetage,
                quantite=2,
            )
        ],
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer_validation(piece: PieceExtraite) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece, matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {"client_id": None, "quantites": [100], "nom_modele": "t"}
    return at.run()


def _blocs_ventilation(at: AppTest) -> list[str]:
    for tableau in at.dataframe:
        df = tableau.value
        if "Bloc" in df.columns:
            return list(df["Bloc"])
    raise AssertionError("Tableau « D'où viennent les coûts ? » absent")


def test_candidat_unique_preselectionne_et_chiffre():
    """Écrou M4 : seule référence ES-M4-A → pré-sélectionnée, bloc 6 chiffré."""
    at = _lancer_validation(piece_support("M4"))

    assert not at.exception, [e.value for e in at.exception]
    assert any("choisissez la référence du référentiel" in c.value for c in at.caption)
    assert not [w.value for w in at.warning if "Composant non chiffré" in w.value]
    assert BLOC_COMPOSANTS in _blocs_ventilation(at)
    assert any(b.label == "Valider la pièce" for b in at.button)


def test_plusieurs_candidats_avertissement_non_bloquant():
    """Écrou M6 : 3 références possibles → rien de choisi, ⚠️ en tête, devis validable."""
    at = _lancer_validation(piece_support("M6"))

    assert not at.exception, [e.value for e in at.exception]
    avertissements = [w.value for w in at.warning if "Composant non chiffré" in w.value]
    assert len(avertissements) == 1
    assert "Écrou à sertir M6 × 2" in avertissements[0]
    # Non bloquant : chiffrage présent (sans bloc 6), pas d'erreur de saisie.
    assert not [e.value for e in at.error if "Saisie incomplète" in e.value]
    assert BLOC_COMPOSANTS not in _blocs_ventilation(at)
    assert any(b.label == "Valider la pièce" for b in at.button)


def _editer_tableau_composants(at: AppTest, edition: dict) -> None:
    """Simule une saisie navigateur dans le data_editor (non pilotable par AppTest).

    Passe par l'API interne d'AppTest : on rejoue le script avec un état de
    widget JSON, exactement ce que le navigateur envoie.
    """
    etat = object.__getattribute__(at.session_state, "_state")
    etat = getattr(etat, "_state", etat)
    wid = etat._key_id_mapper.get_id_from_key("editeur_composants")
    etats = WidgetStates()
    etats.widgets.extend(
        [w for w in at._tree.get_widget_states().widgets if w.id != wid]
        + [WidgetState(id=wid, string_value=json.dumps(edition))]
    )
    at._run(etats)


def test_correction_ia_acceptee_non_masquee_par_une_saisie():
    """Quantité saisie à 3, puis l'assistant corrige à 4 : le chiffrage suit la correction."""
    at = _lancer_validation(piece_support("M6"))
    libelle = "ES-M6-A — Écrou à sertir M6 (0,20 €/u)"
    _editer_tableau_composants(
        at,
        {
            "edited_rows": {"0": {"quantite": 3, "reference": libelle}},
            "added_rows": [],
            "deleted_rows": [],
        },
    )
    prix_saisie = at.table[0].value["Coût unitaire (€)"].iloc[0]

    at.session_state[CLE_PROPOSITION] = PropositionCorrection(
        diffs=[
            DiffCorrection(
                type="modification_element",
                chemin="composants[0]",
                nouvelle_valeur={"quantite": 4},
            )
        ]
    )
    at.run()
    next(b for b in at.button if "Accepter" in b.label).click().run()

    assert not at.exception, [e.value for e in at.exception]
    # La saisie manuelle est oubliée (référence à rechoisir, ⚠️ visible),
    # jamais appliquée en silence à la place de la correction acceptée.
    assert at.session_state["editeur_composants"]["edited_rows"] == {}
    avertissements = [w.value for w in at.warning if "Composant non chiffré" in w.value]
    assert avertissements and "× 4" in avertissements[0]
    assert at.table[0].value["Coût unitaire (€)"].iloc[0] != prix_saisie
