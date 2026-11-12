"""Acceptance #66 : rayon de pliage aberrant signalé, vraie raison du modèle 3D.

Test de bout en bout avec ``streamlit.testing.v1.AppTest`` : la pièce extraite
est déposée dans ``session_state`` comme le fait l'écran de dépôt
(``CLE_RESULTAT`` → ``ResultatDevis``, ``CLE_CONTEXTE``), puis ``main()``
route vers l'écran de validation. La base locale seedée (``data/devis.db``,
via ``get_session``) est utilisée telle quelle (lecture seule).

Pièce support (ailes 42/22/18, cotes extérieures), S235JR, e = 2, rayon
général 50 mm lu sur le plan. Avant le correctif : aucun constat, prix
affiché, et « Pas de profil de pliage » à la place du modèle 3D.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from generateur_devis.schema.piece import (
    Aile,
    Champ,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
)
from generateur_devis.ui.app import CLE_CONTEXTE, CLE_RESULTAT
from generateur_devis.ui.pipeline import ResultatDevis

LABEL_RAYON = "Rayon de pliage général (mm)"


def piece_rayon_50() -> PieceExtraite:
    return PieceExtraite(
        matiere=Matiere(
            designation=Champ[str](valeur="S235JR"), epaisseur=Champ[float](valeur=2.0)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=60.0)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=50.0,
            elements=[
                Aile(longueur=42.0),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=22.0),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=18.0),
            ],
        ),
    )


def _app() -> None:
    from generateur_devis.ui.app import main

    main()


def _lancer_validation() -> AppTest:
    at = AppTest.from_function(_app, default_timeout=30)
    at.session_state[CLE_RESULTAT] = ResultatDevis(piece=piece_rayon_50(), matiere_id="S235JR")
    at.session_state[CLE_CONTEXTE] = {
        "client_id": None,
        "quantites": [1, 100],
        "nom_modele": "test",
    }
    return at.run()


def _prix_affiche(at: AppTest) -> bool:
    return any(c.value == "Prix provisoire" for c in at.caption)


def test_rayon_aberrant_bloque_le_chiffrage_et_explique_la_3d():
    at = _lancer_validation()
    assert not at.exception, [e.value for e in at.exception]

    # ⛔ rayon plus grand que l'aile adjacente (22 et 18 mm), ⚠️ rayon > 8 × e.
    blocages = [e.value for e in at.error if "rayon_aile" in e.value]
    assert len(blocages) == 2, [e.value for e in at.error]
    assert "aile adjacente de 22 mm" in blocages[0]
    assert "aile adjacente de 18 mm" in blocages[1]
    assert [w.value for w in at.warning if "rayon_max" in w.value]

    # Pas de prix tant que la pièce est irréalisable…
    assert not _prix_affiche(at)
    valider = [b for b in at.button if b.label == "Valider la pièce"]
    assert all(b.disabled for b in valider)
    # …mais le formulaire reste éditable, rayon compris.
    rayon = next(n for n in at.number_input if n.label == LABEL_RAYON)
    assert rayon.value == 50.0

    # Vraie raison de l'absence de 3D : le profil existe.
    infos = [i.value for i in at.info]
    assert not [i for i in infos if "Pas de profil de pliage" in i], infos
    raisons = [i for i in infos if "Modèle 3D non représentable" in i]
    assert len(raisons) == 1, infos
    assert "Cotes contradictoires : l'aile n°2 (22 mm)" in raisons[0]


def test_rayon_corrige_debloque_prix_et_3d():
    at = _lancer_validation()
    rayon = next(n for n in at.number_input if n.label == LABEL_RAYON)
    rayon.set_value(2.0).run()

    assert not at.exception, [e.value for e in at.exception]
    assert not [e for e in at.error if "rayon_aile" in e.value]
    assert not [w for w in at.warning if "rayon_max" in w.value]
    assert _prix_affiche(at)
    assert not [i for i in at.info if "Modèle 3D non représentable" in i.value]
