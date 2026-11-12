"""Tests du pipeline d'orchestration (issue #23) — fonction pure, sans Streamlit.

L'extraction IA est remplacée par un bouchon (monkeypatch sur
``charger_plan`` / ``extraire`` du module pipeline) : le pipeline enchaîne
géométrie → faisabilité → chiffrage → contrôles sur la base seedée.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generateur_devis.data.seed import seed
from generateur_devis.data.tables import Base
from generateur_devis.extraction import ResultatExtraction
from generateur_devis.schema.piece import (
    Aile,
    Anomalie,
    Champ,
    CoinCoupe,
    Contours,
    Encombrement,
    Matiere,
    PieceExtraite,
    Pli,
    ProfilPliage,
    Trou,
    Unite,
)
from generateur_devis.ui import pipeline
from generateur_devis.ui.pipeline import anomalie_document, orchestrer_devis, rechiffrer

MATIERE = "S235JR"


def piece_support(matiere: str | None = None) -> PieceExtraite:
    """Le « SUPPORT » du §8 : Z, 2 plis 90°, R 2 mm, cotes extérieures."""
    return PieceExtraite(
        matiere=Matiere(designation=Champ[str](valeur=matiere), epaisseur=Champ[float](valeur=2.0)),
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
            trous=[
                Trou(forme="rond", diametre=8.75, quantite=2),
                Trou(forme="rond", diametre=7.5, quantite=2),
            ],
            coins=[
                CoinCoupe(type="chanfrein", cote1=20.0, quantite=2),
                CoinCoupe(type="chanfrein", cote1=5.0, quantite=2),
            ],
        ),
    )


def _bouchon_extraction(monkeypatch, piece: PieceExtraite | None, erreur: str | None = None):
    """Remplace charger_plan / extraire par un résultat d'extraction fixe."""
    monkeypatch.setattr(pipeline, "charger_plan", lambda chemin: object())

    def faux_extraire(document, modele, **kwargs):
        return ResultatExtraction("test:modele", "test", piece, erreur)

    monkeypatch.setattr(pipeline, "extraire", faux_extraire)
    monkeypatch.setattr(pipeline, "creer_modele", lambda nom: object())


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    seed(session)
    yield session
    session.close()


def test_pipeline_bout_en_bout_pdf_reel(monkeypatch, session, tmp_path):
    """Bout en bout : vrai PDF → vrai ``charger_plan`` (PyMuPDF) → pipeline.

    Seul l'appel IA est bouchonné : la chaîne fichier temporaire →
    chargement du document → géométrie → faisabilité → chiffrage est réelle.
    """
    import pymupdf

    chemin_pdf = tmp_path / "support.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "SUPPORT — S235JR — 2 mm")
        doc.save(chemin_pdf)
    contenu = chemin_pdf.read_bytes()

    piece = piece_support(MATIERE)

    def faux_extraire(document, modele, **kwargs):
        # Le vrai charger_plan a produit un Plan avec images et texte.
        assert document.images and "S235JR" in document.texte
        return ResultatExtraction("test:modele", "test", piece, None)

    monkeypatch.setattr(pipeline, "extraire", faux_extraire)
    monkeypatch.setattr(pipeline, "creer_modele", lambda nom: object())

    resultat = orchestrer_devis(contenu, "support.pdf", None, None, None, "test:m", session)
    assert resultat.erreur is None
    assert resultat.chiffrage is not None
    assert resultat.flan is not None


def test_pipeline_complet_matiere_du_plan(monkeypatch, session):
    """Matière lue sur le plan → chiffrage provisoire complet avec contrôles."""
    _bouchon_extraction(monkeypatch, piece_support(MATIERE))
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, None, "test:m", session)
    assert resultat.erreur is None
    assert resultat.matiere_id == MATIERE
    assert resultat.flan is not None
    assert resultat.chiffrage is not None
    palier_100 = next(p for p in resultat.chiffrage.paliers if p.quantite == 100)
    # Sans composants (références non extraites — tranché en 3.2) : ≈ 1,25 €.
    assert palier_100.cout_unitaire_eur == pytest.approx(1.25, abs=0.03)


def test_pipeline_matiere_fournie(monkeypatch, session):
    """Matière absente du plan mais fournie au contexte → chiffrage calculé."""
    _bouchon_extraction(monkeypatch, piece_support(None))
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, MATIERE, "test:m", session)
    assert resultat.erreur is None
    assert resultat.matiere_id == MATIERE
    assert resultat.chiffrage is not None


def test_pipeline_sans_matiere_resultat_partiel(monkeypatch, session):
    """Matière ni extraite ni fournie → résultat partiel, chiffrage différé (4.3)."""
    _bouchon_extraction(monkeypatch, piece_support(None))
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, None, "test:m", session)
    assert resultat.erreur is None
    assert resultat.piece is not None
    assert resultat.matiere_id is None
    assert resultat.chiffrage is None
    assert resultat.flan is None


def test_pipeline_matiere_inconnue(monkeypatch, session):
    _bouchon_extraction(monkeypatch, piece_support(None))
    resultat = orchestrer_devis(
        b"%PDF-fake", "support.pdf", None, None, "UNOBTANIUM", "test:m", session
    )
    assert resultat.erreur is not None
    assert "Matière inconnue" in resultat.erreur
    assert resultat.piece is not None


def test_pipeline_echec_extraction(monkeypatch, session):
    _bouchon_extraction(monkeypatch, None, erreur="plan illisible")
    resultat = orchestrer_devis(b"%PDF-fake", "scan.jpg", None, None, None, "test:m", session)
    assert resultat.erreur is not None
    assert "plan illisible" in resultat.erreur
    assert resultat.piece is None


def test_pipeline_format_non_supporte(monkeypatch, session):
    def faux_charger(chemin):
        raise ValueError("Format non supporté : .docx")

    monkeypatch.setattr(pipeline, "charger_plan", faux_charger)
    resultat = orchestrer_devis(b"doc", "plan.docx", None, None, None, "test:m", session)
    assert resultat.erreur == "Format non supporté : .docx"


def test_pipeline_blocage_faisabilite_pas_de_chiffrage(monkeypatch, session):
    """Épaisseur hors gamme → blocage faisabilité, chiffrage non calculé."""
    piece = piece_support(MATIERE).model_copy(deep=True)
    piece.matiere.epaisseur.valeur = 7.0  # non disponible pour S235JR → blocage
    _bouchon_extraction(monkeypatch, piece)
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, None, "test:m", session)
    assert resultat.bloque
    assert resultat.chiffrage is None
    assert resultat.alertes_controles == []


def test_pipeline_quantites_personnalisees(monkeypatch, session):
    _bouchon_extraction(monkeypatch, piece_support(MATIERE))
    resultat = orchestrer_devis(
        b"%PDF-fake", "support.pdf", None, [50, 500], None, "test:m", session
    )
    assert [p.quantite for p in resultat.chiffrage.paliers] == [50, 500]


def test_pipeline_client_marge_specifique(monkeypatch, session):
    """CLI001 (marge 18 %) : le prix provisoire applique sa marge."""
    _bouchon_extraction(monkeypatch, piece_support(MATIERE))
    resultat = orchestrer_devis(
        b"%PDF-fake", "support.pdf", "CLI001", [100], None, "test:m", session
    )
    palier = resultat.chiffrage.paliers[0]
    assert palier.prix_unitaire_eur == pytest.approx(palier.cout_unitaire_eur / 0.82, rel=1e-9)


# --- Plans en pouces (issue #57) ---------------------------------------------


def piece_umaine_pouces() -> PieceExtraite:
    """Le support coté en pouces : épaisseur 0,06 in (cas UMaine)."""
    return PieceExtraite(
        unites=Champ[Unite](valeur="in"),
        matiere=Matiere(
            designation=Champ[str](valeur=MATIERE), epaisseur=Champ[float](valeur=0.06)
        ),
        encombrement=Encombrement(largeur=Champ[float](valeur=2.36)),
        profil_pliage=ProfilPliage(
            cotation="exterieure",
            rayon_pliage_general=0.08,
            elements=[
                Aile(longueur=1.65),
                Pli(angle=90.0, sens="haut"),
                Aile(longueur=0.87),
                Pli(angle=90.0, sens="bas"),
                Aile(longueur=0.71),
            ],
        ),
        contours=Contours(trous=[Trou(forme="rond", diametre=0.75, quantite=2)]),
    )


def test_pipeline_plan_en_pouces_converti_avant_geometrie(monkeypatch, session):
    """0,06 in → 1,524 mm : géométrie et faisabilité reçoivent des mm, rien n'est arrondi."""
    _bouchon_extraction(monkeypatch, piece_umaine_pouces())
    resultat = orchestrer_devis(b"%PDF-fake", "umaine.pdf", None, None, None, "test:m", session)

    assert resultat.erreur is None
    assert resultat.piece.unites.valeur == "mm"
    assert resultat.piece.matiere.epaisseur.valeur == pytest.approx(1.524)
    assert resultat.piece.contours.trous[0].diametre == pytest.approx(19.05)
    # La géométrie a travaillé en mm (2,36 in = 59,944 mm ; 0,06 in = 1,524 mm).
    assert resultat.flan.largeur_mm == pytest.approx(59.944)
    assert resultat.flan.epaisseur_mm == pytest.approx(1.524)
    # Pas d'arrondi vers l'épaisseur du stock : la faisabilité bloque proprement.
    assert [c.regle for c in resultat.constats if c.severite == "blocage"] == ["epaisseur_dispo"]
    blocage = next(c for c in resultat.constats if c.regle == "epaisseur_dispo")
    assert blocage.message.startswith("Épaisseur 1.524 mm non disponible pour S235JR")
    assert resultat.chiffrage is None
    # Trace de la conversion.
    assert resultat.conversion.unite_origine == "in"
    traces = {v.chemin: (v.valeur_origine, v.valeur_mm) for v in resultat.conversion.valeurs}
    assert traces["matiere.epaisseur.valeur"] == (0.06, pytest.approx(1.524))
    assert traces["encombrement.largeur.valeur"] == (2.36, pytest.approx(59.944))
    assert traces["profil_pliage.rayon_pliage_general"] == (0.08, pytest.approx(2.032))
    assert len(resultat.conversion.valeurs) == 7


def test_pipeline_pouces_sans_matiere_conversion_tracee(monkeypatch, session):
    """Résultat partiel (matière absente) : pièce convertie et trace transmises."""
    piece = piece_umaine_pouces()
    piece.matiere.designation.valeur = None
    _bouchon_extraction(monkeypatch, piece)
    resultat = orchestrer_devis(b"%PDF-fake", "umaine.pdf", None, None, None, "test:m", session)
    assert resultat.chiffrage is None
    assert resultat.piece.matiere.epaisseur.valeur == pytest.approx(1.524)
    assert resultat.conversion.unite_origine == "in"


def test_pipeline_unite_non_lue_aucune_conversion(monkeypatch, session):
    """piece_support (unites null) : rien de converti, chiffrage inchangé (non-régression)."""
    _bouchon_extraction(monkeypatch, piece_support(MATIERE))
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, None, "test:m", session)
    assert resultat.conversion.unite_origine is None
    assert resultat.conversion.valeurs == []
    assert resultat.piece == piece_support(MATIERE)
    assert resultat.chiffrage is not None


def test_pipeline_echec_extraction_sans_conversion(monkeypatch, session):
    _bouchon_extraction(monkeypatch, None, erreur="JSON invalide")
    resultat = orchestrer_devis(b"%PDF-fake", "support.pdf", None, None, None, "test:m", session)
    assert resultat.conversion is None


# --- rechiffrer avec composants rattachés (issue #56) ------------------------


def test_rechiffrer_avec_composants_rattaches(session):
    """SUPPORT + 2 × ES-M6-A : coût Q=100 ≈ 2,20 € (docs/logique_metier.md §8)."""
    from generateur_devis.ui.ventilation import ventilation_couts

    resultat = rechiffrer(
        piece_support(MATIERE), MATIERE, None, None, session, composants=[("ES-M6-A", 2)]
    )
    assert resultat.erreur is None
    assert resultat.chiffrage is not None
    palier_100 = next(p for p in resultat.chiffrage.paliers if p.quantite == 100)
    assert palier_100.cout_unitaire_eur == pytest.approx(2.20, abs=0.03)
    blocs = {ligne["bloc"] for ligne in ventilation_couts(resultat.chiffrage)}
    assert "Composants & opérations" in blocs


def test_rechiffrer_sans_composants_inchange(session):
    """Défaut : aucun composant transmis → ≈ 1,25 € (non-régression)."""
    resultat = rechiffrer(piece_support(MATIERE), MATIERE, None, None, session)
    palier_100 = next(p for p in resultat.chiffrage.paliers if p.quantite == 100)
    assert palier_100.cout_unitaire_eur == pytest.approx(1.25, abs=0.03)


@pytest.mark.parametrize(("contenu", "nom"), [(b"", "vide.pdf"), (b"hello world", "faux.pdf")])
def test_pipeline_fichier_illisible_sans_appel_modele(monkeypatch, session, contenu, nom):
    """Issue #63 : vrai ``charger_plan`` ; le modèle ne doit jamais être sollicité."""

    def interdit(*args, **kwargs):
        raise AssertionError("modèle appelé")

    monkeypatch.setattr(pipeline, "extraire", interdit)
    monkeypatch.setattr(pipeline, "creer_modele", interdit)

    resultat = orchestrer_devis(contenu, nom, None, None, None, "test:m", session)

    assert resultat.erreur == "Fichier illisible ou vide : déposez un PDF ou une image de plan."
    assert resultat.piece is None
    assert "/" not in resultat.erreur and "tmp" not in resultat.erreur


# --- Document non exploitable signalé par l'IA (issue #64) -----------------------


def _avec_anomalies(piece: PieceExtraite, *anomalies: Anomalie) -> PieceExtraite:
    piece.anomalies = list(anomalies)
    return piece


DOCUMENT = Anomalie(type="illisible", champ="document", description="devis commercial")


def test_anomalie_document_renvoyee():
    piece = _avec_anomalies(piece_support(MATIERE), DOCUMENT)
    assert anomalie_document(piece) == DOCUMENT


def test_anomalie_document_premiere_seulement():
    seconde = Anomalie(type="illisible", champ="document", description="facture")
    piece = _avec_anomalies(piece_support(MATIERE), DOCUMENT, seconde)
    assert anomalie_document(piece) == DOCUMENT


@pytest.mark.parametrize(
    "anomalie",
    [
        Anomalie(type="illisible", champ=None, description="tache sur le cartouche"),
        Anomalie(type="illisible", champ="matiere.designation", description="matière floue"),
        Anomalie(type="autre", champ="document", description="plan scanné de travers"),
    ],
)
def test_anomalie_document_ignore_les_autres_anomalies(anomalie):
    assert anomalie_document(_avec_anomalies(piece_support(MATIERE), anomalie)) is None


def test_anomalie_document_sans_anomalie():
    assert anomalie_document(piece_support(MATIERE)) is None


@pytest.mark.parametrize("matiere_id", [None, MATIERE])
def test_pipeline_document_non_plan_refuse(monkeypatch, session, matiere_id):
    """Refus avant matière et géométrie, même avec une matière choisie au dépôt."""
    _bouchon_extraction(monkeypatch, _avec_anomalies(piece_support(MATIERE), DOCUMENT))

    resultat = orchestrer_devis(b"%PDF", "devis.pdf", None, None, matiere_id, "test:m", session)

    assert resultat.piece is None
    assert resultat.chiffrage is None
    assert resultat.flan is None
    assert resultat.erreur == (
        "Ce document n'est pas un plan exploitable : devis commercial "
        "Déposez le plan de la pièce (PDF ou image)."
    )


def test_pipeline_anomalie_illisible_ordinaire_chiffre(monkeypatch, session):
    """Une zone illisible sur un vrai plan n'empêche pas le chiffrage."""
    anomalie = Anomalie(type="illisible", champ="matiere.designation", description="floue")
    _bouchon_extraction(monkeypatch, _avec_anomalies(piece_support(MATIERE), anomalie))

    resultat = orchestrer_devis(b"%PDF", "plan.pdf", None, None, None, "test:m", session)

    assert resultat.erreur is None
    assert resultat.piece is not None
    assert resultat.piece.anomalies == [anomalie]
    assert resultat.chiffrage is not None
