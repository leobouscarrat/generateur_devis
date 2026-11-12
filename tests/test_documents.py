"""Tests de `charger_plan` sur des fichiers vides ou illisibles (issue #63).

Vrais fichiers dans ``tmp_path``, vrai PyMuPDF, sans bouchon.
"""

import os

import pymupdf
import pytest

from generateur_devis.extraction.documents import FICHIER_ILLISIBLE, charger_plan

# PDF syntaxiquement valide mais sans aucune page (pymupdf refuse d'en sauvegarder un).
PDF_SANS_PAGE = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


@pytest.mark.parametrize(
    ("nom", "contenu"),
    [
        ("vide.pdf", b""),
        ("faux.pdf", b"hello world"),
        ("vide.png", b""),
        ("vide.jpg", b""),
        ("vide.webp", b""),
        ("corrompu.png", os.urandom(300)),
        ("sans_page.pdf", PDF_SANS_PAGE),
    ],
)
def test_fichier_illisible_message_unique_sans_chemin(tmp_path, nom, contenu):
    chemin = tmp_path / nom
    chemin.write_bytes(contenu)

    with pytest.raises(ValueError) as exc:
        charger_plan(chemin)

    message = str(exc.value)
    assert message == "Fichier illisible ou vide : déposez un PDF ou une image de plan."
    assert message == FICHIER_ILLISIBLE
    assert str(tmp_path) not in message
    assert nom not in message
    # Aucune chaîne affichée vers l'erreur PyMuPDF (relance « from None »).
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None or exc.value.__suppress_context__


def test_format_non_supporte_inchange(tmp_path):
    chemin = tmp_path / "plan.docx"
    chemin.write_bytes(b"")  # vide : le contrôle d'extension passe en premier
    with pytest.raises(ValueError, match="Format non supporté : .docx"):
        charger_plan(chemin)


def test_png_valide_charge(tmp_path):
    with pymupdf.open() as doc:
        page = doc.new_page(width=100, height=50)
        octets = page.get_pixmap().tobytes("png")
    chemin = tmp_path / "plan.png"
    chemin.write_bytes(octets)

    plan = charger_plan(chemin)

    assert len(plan.images) == 1
    assert plan.images[0].donnees == octets  # octets d'origine, non ré-encodés
    assert plan.images[0].type_mime == "image/png"
    assert plan.texte == ""


def test_jpeg_valide_charge(tmp_path):
    with pymupdf.open() as doc:
        octets = doc.new_page(width=100, height=50).get_pixmap().tobytes("jpg")
    chemin = tmp_path / "plan.jpg"
    chemin.write_bytes(octets)

    plan = charger_plan(chemin)

    assert plan.images[0].donnees == octets
    assert plan.images[0].type_mime == "image/jpeg"


def test_webp_valide_charge(tmp_path):
    """MuPDF ne décode pas le WEBP : un WEBP valide ne doit pas être refusé."""
    # WEBP lossless 2×2 rouge (généré par Pillow, octets figés).
    octets = (
        b"RIFF\x1c\x00\x00\x00WEBPVP8L\x0f\x00\x00\x00/\x01@\x00\x00"
        b'\x07\x10\xfd\x8f\xfe\x07"\xa2\xff\x01\x00'
    )
    chemin = tmp_path / "plan.webp"
    chemin.write_bytes(octets)

    plan = charger_plan(chemin)

    assert plan.images[0].donnees == octets
    assert plan.images[0].type_mime == "image/webp"


def test_pdf_valide_charge(tmp_path):
    chemin = tmp_path / "plan.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "SUPPORT S235JR")
        doc.save(chemin)

    plan = charger_plan(chemin)

    assert len(plan.images) == 1
    assert plan.images[0].type_mime == "image/png"
    assert "SUPPORT S235JR" in plan.texte
