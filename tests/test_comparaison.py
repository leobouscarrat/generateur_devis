from generateur_devis.evaluation.comparaison import comparer, normaliser
from generateur_devis.evaluation.executer import intervalle_wilson
from generateur_devis.schema import (
    Aile,
    Anomalie,
    Champ,
    Cote,
    Matiere,
    Note,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Traitement,
)


def statut(verite, extraction, champ):
    (resultat,) = comparer(verite, extraction, [champ])
    return resultat


def test_normalisation_textes():
    assert normaliser("ISO 2768 -m") == normaliser("ISO 2768-m")
    assert normaliser("FILETAGES") == normaliser("filetages")
    assert normaliser("Épargne") == normaliser("EPARGNE")


def test_valeur_juste_et_fausse():
    verite = PieceExtraite(matiere=Matiere(epaisseur=Champ(valeur=2.0)))
    assert statut(verite, verite, "matiere.epaisseur").statut == "juste"
    autre = PieceExtraite(matiere=Matiere(epaisseur=Champ(valeur=3.0)))
    assert statut(verite, autre, "matiere.epaisseur").statut == "faux"
    assert statut(verite, PieceExtraite(), "matiere.epaisseur").statut == "manquant"


def test_invention_et_deduction_signalee():
    verite = PieceExtraite()  # aucun traitement sur le plan
    invente = PieceExtraite(traitement=Traitement(type=Champ(valeur="aucun", confiance=0.9)))
    assert statut(verite, invente, "traitement.type").statut == "invente"
    deduit = PieceExtraite(
        traitement=Traitement(type=Champ(valeur="peinture", confiance=0.9)),
        anomalies=[
            Anomalie(type="autre", champ="traitement.type", description="déduit d'une note")
        ],
    )
    assert statut(verite, deduit, "traitement.type").statut == "deduit_signale"
    assert statut(verite, PieceExtraite(), "traitement.type").statut == "absent_ok"


def test_profil_accepte_dans_les_deux_sens():
    z = [Aile(longueur=18), Pli(angle=90), Aile(longueur=22), Pli(angle=90), Aile(longueur=42)]
    verite = PieceExtraite(profil_pliage=ProfilPliage(elements=z))
    inverse = PieceExtraite(profil_pliage=ProfilPliage(elements=list(reversed(z))))
    assert statut(verite, inverse, "profil_pliage").statut == "juste"
    faux = [Aile(longueur=42), Pli(angle=90), Aile(longueur=22), Pli(angle=90), Aile(longueur=60)]
    assert (
        statut(
            verite, PieceExtraite(profil_pliage=ProfilPliage(elements=faux)), "profil_pliage"
        ).statut
        == "faux"
    )


def test_liste_de_cotes():
    verite = PieceExtraite(cotes=[Cote(valeur=v) for v in (60, 60, 42, 2)])
    lue = PieceExtraite(cotes=[Cote(valeur=v) for v in (60, 42, 2, 99)])
    r = statut(verite, lue, "cotes")
    assert (r.apparies, r.attendus, r.lus) == (3, 4, 4)


def test_notes_proches_acceptees():
    verite = PieceExtraite(notes=[Note(texte="DEBURR ALL EDGES", categorie="general")])
    lue = PieceExtraite(notes=[Note(texte="1. DEBURR ALL EDGES.", categorie="operation")])
    assert statut(verite, lue, "notes").apparies == 1


def test_intervalle_wilson():
    bas, haut = intervalle_wilson(40, 50)
    assert 0.66 < bas < 0.70 and 0.88 < haut < 0.91
