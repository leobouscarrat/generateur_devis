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
    Composant,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Source,
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


def test_ajout_element_trous(monkeypatch):
    """Cas utilisateur : « 2 trous Ø8.75 » non extraits → ajout via contours.trous."""
    piece = piece_support().model_copy(update={
        "contours": Contours(coins=[CoinCoupe(type="chanfrein", cote1=20.0, quantite=2)])
    })
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "ajout_element", "chemin": "contours.trous",
             "nouvelle_valeur": {"forme": "rond", "diametre": 8.75, "quantite": 2},
             "justification": "2 trous Ø8.75 sur le plan"}
        ]
    })
    proposition = proposer_correction(piece, "il y a 2 trous Ø8.75", "test")
    lignes = proposition.ligne_avant_apres(piece)
    assert lignes[0][:3] == (
        "Trou (ajout)", "—", "Forme : rond, Diamètre (mm) : 8.75, Quantité : 2"
    )

    corrigee = proposition.appliquer(piece)
    assert len(corrigee.contours.trous) == 1
    assert corrigee.contours.trous[0].diametre == 8.75
    assert corrigee.contours.trous[0].quantite == 2
    assert len(corrigee.contours.coins) == 1  # le reste de la fiche est préservé
    assert len(piece.contours.trous) == 0  # l'originale n'est jamais modifiée


def test_ajout_element_liste_non_enrichissable_rejetee(monkeypatch):
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "ajout_element", "chemin": "tolerances_geometriques",
             "nouvelle_valeur": {}, "justification": "?"}
        ]
    })
    with pytest.raises(ErreurCorrection, match="non enrichissable"):
        proposer_correction(piece_support(), "ajoute une tolérance", "test")


def test_ajout_element_invalide_rejete_a_l_application():
    """Un élément invalide (quantité nulle) est rejeté."""
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="ajout_element", chemin="contours.trous",
        nouvelle_valeur={"forme": "rond", "diametre": 8.0, "quantite": 0},
        justification="?",
    )])
    with pytest.raises(ErreurCorrection, match="invalide"):
        proposition.appliquer(piece_support())


def test_modification_element_trou_oblong_vers_rond():
    """Cas réel : trou lu « oblong » (largeur 0.1935) → c'est un perçage rond Ø0.1935."""
    piece = piece_support().model_copy(update={
        "contours": Contours(trous=[Trou(forme="oblong", largeur=0.1935, quantite=4)])
    })
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin="contours.trous[0]",
        nouvelle_valeur={"forme": "rond", "diametre": 0.1935, "largeur": None, "longueur": None},
        justification="perçage #10",
    )])
    corrigee = proposition.appliquer(piece)
    trou = corrigee.contours.trous[0]
    assert trou.forme == "rond" and trou.diametre == 0.1935
    assert trou.largeur is None and trou.quantite == 4  # quantité conservée
    assert piece.contours.trous[0].forme == "oblong"  # l'originale est intacte


def test_modification_element_sens_du_pli():
    """Cas réel : le pli est vers le haut → sens « inconnu » → « haut »."""
    piece = piece_support()
    piece.profil_pliage.elements[1].sens = "inconnu"
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin="profil_pliage.elements[1]",
        nouvelle_valeur={"sens": "haut"},
        justification="le pli est vers le haut",
    )])
    corrigee = proposition.appliquer(piece)
    assert corrigee.profil_pliage.elements[1].sens == "haut"
    assert corrigee.profil_pliage.elements[1].angle == 90.0  # conservé


def test_modification_element_index_hors_liste_rejete_avant_affichage(monkeypatch):
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "modification_element", "chemin": "contours.trous[9]",
             "nouvelle_valeur": {"forme": "rond"}, "justification": "?"}
        ]
    })
    with pytest.raises(ErreurCorrection, match="hors de la liste"):
        proposer_correction(piece_support(), "corrige le trou", "test")


def test_modification_element_champ_inconnu_rejete():
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin="contours.trous[0]",
        nouvelle_valeur={"couleur": "rouge"}, justification="?",
    )])
    with pytest.raises(ErreurCorrection, match="inconnu"):
        proposition.appliquer(piece_support())


def test_modification_element_resultat_invalide_rejete():
    """Fusion valide champ par champ mais élément résultant invalide (quantité 0)."""
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin="contours.trous[0]",
        nouvelle_valeur={"quantite": 0}, justification="?",
    )])
    with pytest.raises(ErreurCorrection, match="invalide"):
        proposition.appliquer(piece_support())


def test_modification_element_avant_apres_affiche_element_actuel():
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin="profil_pliage.elements[1]",
        nouvelle_valeur={"sens": "bas"}, justification="?",
    )])
    lignes = proposition.ligne_avant_apres(piece_support())
    # Seul le champ modifié est affiché, avec la position de l'élément (#67).
    assert lignes == [("Profil, élément 2 (pli) : Sens", "haut", "bas", "?")]


def test_ajout_composant_reste_accepte():
    """Rétrocompatibilité : l'ancien type ajout_composant fonctionne toujours."""
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="ajout_composant", chemin=None,
        nouvelle_valeur={"designation": "Écrou M6", "type": "ecrou_a_sertir",
                         "filetage": "M6", "quantite": 4},
        justification="?",
    )])
    corrigee = proposition.appliquer(piece_support())
    assert len(corrigee.composants) == 1
    assert corrigee.composants[0].designation == "Écrou M6"


def test_sections_creables_couvrent_toutes_les_sections_optionnelles():
    """Garde-fou d'extension : toute section nullable du schéma doit être dans
    SECTIONS_CREABLES (aujourd'hui : uniquement profil_pliage). Si une nouvelle
    section optionnelle apparaît dans PieceExtraite, ce test échoue tant qu'elle
    n'est pas déclarée créable."""
    from generateur_devis.extraction.correction import SECTIONS_CREABLES

    optionnelles = {
        nom
        for nom, champ in PieceExtraite.model_fields.items()
        if champ.default is None  # default_factory → PydanticUndefined, pas None
    }
    assert optionnelles == set(SECTIONS_CREABLES)


PROFIL_A_CREER = {
    "cotation": "exterieure",
    "rayon_pliage_general": 2.0,
    "elements": [
        {"type": "aile", "longueur": 42.0},
        {"type": "pli", "angle": 90.0, "sens": "haut"},
        {"type": "aile", "longueur": 22.0},
    ],
}


def test_creation_section_profil_pliage_absent(monkeypatch):
    """Pli non extrait → le texte décrit le profil → l'assistant crée la section."""
    piece = piece_support().model_copy(update={"profil_pliage": None})
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "creation_section", "chemin": "profil_pliage",
             "nouvelle_valeur": PROFIL_A_CREER,
             "justification": "1 pli 90° haut, rayon 2 mm, cotes extérieures"}
        ]
    })
    proposition = proposer_correction(piece, "1 pli à 90° sens haut, rayon 2 mm, cotes extérieures", "test")
    lignes = proposition.ligne_avant_apres(piece)
    assert lignes[0][:2] == ("Profil de pliage", "— (absent)")
    assert "aile 42.00" in lignes[0][2]
    assert "pli 90.00° haut" in lignes[0][2]

    corrigee = proposition.appliquer(piece)
    assert corrigee.profil_pliage is not None
    assert corrigee.profil_pliage.rayon_pliage_general == 2.0
    assert len(corrigee.profil_pliage.elements) == 3
    assert piece.profil_pliage is None  # l'originale n'est jamais modifiée


def test_creation_section_deja_presente_rejetee(monkeypatch):
    """Créer une section déjà présente est rejeté avant affichage."""
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "creation_section", "chemin": "profil_pliage",
             "nouvelle_valeur": PROFIL_A_CREER, "justification": "?"}
        ]
    })
    with pytest.raises(ErreurCorrection, match="existe déjà"):
        proposer_correction(piece_support(), "refais le profil", "test")


def test_creation_section_non_creable_rejetee(monkeypatch):
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "creation_section", "chemin": "contours",
             "nouvelle_valeur": {}, "justification": "?"}
        ]
    })
    with pytest.raises(ErreurCorrection, match="non créable"):
        proposer_correction(piece_support(), "refais les contours", "test")


def test_creation_section_objet_invalide_rejete_a_l_application():
    """Un objet de section invalide est rejeté (aile de longueur négative)."""
    piece = piece_support().model_copy(update={"profil_pliage": None})
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="creation_section", chemin="profil_pliage",
        nouvelle_valeur={"cotation": "exterieure", "elements": [
            {"type": "aile", "longueur": -5.0}
        ]},
        justification="?",
    )])
    with pytest.raises(ErreurCorrection, match="invalide"):
        proposition.appliquer(piece)


def test_chemin_inapplicable_rejete_avant_affichage(monkeypatch):
    """Cas réel du test utilisateur : pli non extrait → profil_pliage null →
    le diff sur profil_pliage.rayon_pliage_general est rejeté avant affichage
    (et non après acceptation, avec « section absente »)."""
    piece = piece_support().model_copy(update={"profil_pliage": None})
    _bouchon_modele(monkeypatch, {
        "diffs": [
            {"type": "remplacement", "chemin": "profil_pliage.rayon_pliage_general",
             "nouvelle_valeur": 2.0, "justification": "rayon 2 mm sur le plan"}
        ]
    })
    with pytest.raises(ErreurCorrection, match="inapplicable"):
        proposer_correction(piece, "1 pli à 90°, rayon 2 mm", "test")


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
    assert lignes == [("Épaisseur (mm)", "2.00", "3.00", "3 mm")]


# --- Avant/après lisible (issue #67) ----------------------------------------

ECROUS = "CRIMPING NUTS M6 1,00 CL8 S2S"


def _piece_avec_ecrous() -> PieceExtraite:
    return piece_support().model_copy(update={"composants": [Composant(
        designation=ECROUS, type="ecrou_a_sertir", filetage="M6", quantite=2,
        confiance=0.9, source=Source(page=1, zone=(0.1, 0.2, 0.3, 0.4)),
    )]})


def _cellules_techniques(lignes) -> list[str]:
    """Cellules contenant un résidu technique (trace, repr Pydantic, dict)."""
    interdits = ("confiance", "source", "Source(", "{", "[")
    return [c for ligne in lignes for c in ligne[:3] if any(i in c for i in interdits)]


def _modif(chemin, valeur, justification="?"):
    return PropositionCorrection(diffs=[DiffCorrection(
        type="modification_element", chemin=chemin,
        nouvelle_valeur=valeur, justification=justification,
    )])


def test_modification_composant_une_ligne_par_champ_modifie():
    lignes = _modif("composants[0]", {"quantite": 4}, "4 écrous").ligne_avant_apres(
        _piece_avec_ecrous()
    )
    assert lignes == [(f"Composant « {ECROUS} » : Quantité", "2", "4", "4 écrous")]
    assert _cellules_techniques(lignes) == []


def test_modification_trou_oblong_vers_rond():
    piece = piece_support().model_copy(update={"contours": Contours(
        trous=[Trou(forme="oblong", longueur=12.0, largeur=8.75, quantite=2)]
    )})
    lignes = _modif(
        "contours.trous[0]", {"forme": "rond", "diametre": 8.75, "longueur": None, "largeur": None}
    ).ligne_avant_apres(piece)
    assert lignes == [
        ("Trou 1 : Forme", "oblong", "rond", "?"),
        ("Trou 1 : Diamètre (mm)", "—", "8.75", "?"),
        ("Trou 1 : Longueur (mm)", "12.00", "—", "?"),
        ("Trou 1 : Largeur (mm)", "8.75", "—", "?"),
    ]


def test_modification_aile_vers_pli_refusee_ligne_de_repli_lisible():
    """Changer le type d'un élément du profil est refusé par appliquer (angle et
    sens inconnus d'une Aile) : l'avant/après le montre en ligne de repli
    lisible, cohérente avec le st.error de l'écran."""
    proposition = _modif(
        "profil_pliage.elements[2]", {"type": "pli", "angle": 90.0, "sens": "bas"}
    )
    lignes = proposition.ligne_avant_apres(piece_support())
    assert lignes == [(
        "profil_pliage.elements[2]", "—", "Type : pli, Angle (°) : 90.00, Sens : bas", "?"
    )]
    with pytest.raises(ErreurCorrection, match="inconnu"):
        proposition.appliquer(piece_support())


def test_modification_sans_changement_reel():
    lignes = _modif("contours.trous[0]", {"quantite": 2}).ligne_avant_apres(piece_support())
    assert lignes == [("Trou 1 : (aucun changement)", "—", "—", "?")]


def test_composant_sans_designation_libelle_par_position():
    piece = _piece_avec_ecrous().model_copy(update={"composants": [
        Composant(designation="  ", type="rivet", quantite=1)
    ]})
    lignes = _modif("composants[0]", {"quantite": 3}).ligne_avant_apres(piece)
    assert lignes[0][0] == "Composant 1 : Quantité"


def test_ajout_composant_resume_lisible_sans_underscore():
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="ajout_composant", chemin=None,
        nouvelle_valeur={"designation": "Écrou M6", "type": "ecrou_a_sertir",
                         "filetage": "M6", "quantite": 4, "confiance": 0.8},
        justification="4 écrous",
    )])
    lignes = proposition.ligne_avant_apres(piece_support())
    assert lignes == [(
        "Composant (ajout)", "—",
        "Désignation : Écrou M6, Type : ecrou a sertir, Filetage : M6, Quantité : 4",
        "4 écrous",
    )]


def test_creation_section_resume_complet():
    piece = piece_support().model_copy(update={"profil_pliage": None})
    proposition = PropositionCorrection(diffs=[DiffCorrection(
        type="creation_section", chemin="profil_pliage", nouvelle_valeur=PROFIL_A_CREER,
    )])
    assert proposition.ligne_avant_apres(piece) == [(
        "Profil de pliage", "— (absent)",
        "Cotation exterieure, rayon général 2.00 mm : aile 42.00 / pli 90.00° haut / aile 22.00",
        "",
    )]


@pytest.mark.parametrize("diff", [
    DiffCorrection(type="modification_element", chemin="composants[5]",
                   nouvelle_valeur={"quantite": 4, "confiance": 0.9}),
    DiffCorrection(type="modification_element", chemin="contours.trous[0]",
                   nouvelle_valeur={"couleur": "rouge", "source": {"page": 1}}),
    DiffCorrection(type="modification_element", chemin="contours.trous[0]",
                   nouvelle_valeur={"quantite": 0}),
    DiffCorrection(type="modification_element", chemin="contours.trous[0]",
                   nouvelle_valeur="rond"),
    DiffCorrection(type="remplacement", chemin="identification.reference.valeur",
                   nouvelle_valeur="X"),
    DiffCorrection(type="remplacement", chemin="matiere.epaisseur.valeur",
                   nouvelle_valeur="épais"),
    DiffCorrection(type="ajout_element", chemin="contours.trous",
                   nouvelle_valeur={"forme": "triangle", "confiance": 0.5}),
    DiffCorrection(type="ajout_element", chemin="notes", nouvelle_valeur={"texte": "x"}),
    DiffCorrection(type="creation_section", chemin="profil_pliage",
                   nouvelle_valeur={"elements": [{"type": "pli", "angle": 0}]}),
    # Revue #80 : liste d'éléments au lieu d'un objet, entier démesuré.
    DiffCorrection(type="ajout_element", chemin="contours.trous",
                   nouvelle_valeur=[{"forme": "rond", "diametre": 8, "confiance": 0.9,
                                     "source": {"page": 1}}]),
    DiffCorrection(type="modification_element", chemin="composants[0]",
                   nouvelle_valeur=[{"quantite": 4, "confiance": 1}]),
    DiffCorrection(type="modification_element", chemin="contours.trous[0]",
                   nouvelle_valeur={"diametre": 10**400}),
])
def test_diff_inapplicable_ligne_de_repli_sans_exception(diff):
    piece = piece_support().model_copy(update={"profil_pliage": None})
    lignes = PropositionCorrection(diffs=[diff]).ligne_avant_apres(piece)
    assert len(lignes) == 1
    assert lignes[0][0] == diff.chemin
    assert lignes[0][1] == "—"
    assert "confiance" not in lignes[0][2] and "source" not in lignes[0][2]
    assert "{" not in lignes[0][2] and "[" not in lignes[0][2]
    # Le diff reste bien refusé à l'application (le st.error fait foi).
    with pytest.raises(ErreurCorrection):
        PropositionCorrection(diffs=[diff]).appliquer(piece)


def test_garde_fou_libelles_chemins_couvrent_la_whitelist():
    from generateur_devis.extraction.correction import CHEMINS_AUTORISES, LIBELLES_CHEMINS

    assert set(LIBELLES_CHEMINS) == set(CHEMINS_AUTORISES)


def test_garde_fou_libelles_listes_couvrent_les_listes_modifiables():
    from generateur_devis.extraction.correction import ELEMENTS_MODIFIABLES, LIBELLES_LISTES

    assert set(LIBELLES_LISTES) == set(ELEMENTS_MODIFIABLES)


def test_garde_fou_libelles_champs_couvrent_les_modeles_d_elements():
    """Tout champ d'un élément modifiable (Aile et Pli inclus) a un libellé."""
    from typing import get_args

    from generateur_devis.extraction.correction import (
        CHAMPS_MASQUES,
        ELEMENTS_MODIFIABLES,
        LIBELLES_CHAMPS_ELEMENT,
    )

    modeles = []
    for modele in ELEMENTS_MODIFIABLES.values():
        if isinstance(modele, type):
            modeles.append(modele)
        else:  # union discriminée Annotated[Aile | Pli, ...]
            modeles.extend(get_args(get_args(modele)[0]))
    assert {m.__name__ for m in modeles} >= {"Aile", "Pli", "Trou", "Composant"}
    for modele in modeles:
        manquants = set(modele.model_fields) - CHAMPS_MASQUES - set(LIBELLES_CHAMPS_ELEMENT)
        assert not manquants, (modele.__name__, manquants)
