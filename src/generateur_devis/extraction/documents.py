"""Chargement d'un plan : PDF ou image → images des pages + texte du PDF s'il existe."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from generateur_devis.llm.base import Image

TYPES_IMAGE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass
class Plan:
    chemin: Path
    images: list[Image]
    texte: str
    """Texte lisible du PDF (vide pour un scan ou une image)."""


FICHIER_ILLISIBLE = "Fichier illisible ou vide : déposez un PDF ou une image de plan."

# Erreurs de PyMuPDF sur un contenu indécodable : EmptyFileError/FileDataError
# (RuntimeError), FzErrorFormat (FzErrorBase), ValueError (image vide).
_ERREURS_LECTURE = (ValueError, RuntimeError, pymupdf.mupdf.FzErrorBase)
# Formats que MuPDF sait décoder : le WEBP n'en fait pas partie (un WEBP valide
# lève FzErrorFormat), il n'est donc contrôlé que sur le fichier vide.
_IMAGES_DECODABLES = {".png", ".jpg", ".jpeg"}


def charger_plan(chemin: Path | str, dpi: int = 150, pages_max: int = 2) -> Plan:
    """Charge un plan PDF ou image.

    Raises:
        ValueError: format non supporté, ou `FICHIER_ILLISIBLE` si le fichier
            est vide, si le PDF ne s'ouvre pas ou n'a aucune page, ou si
            l'image (PNG ou JPEG) ne se décode pas. Le message ne contient jamais le chemin
            du fichier, et l'erreur PyMuPDF d'origine n'est pas chaînée.
    """
    chemin = Path(chemin)
    extension = chemin.suffix.lower()
    if extension not in TYPES_IMAGE and extension != ".pdf":
        raise ValueError(f"Format non supporté : {extension} (PDF, PNG, JPG ou WEBP)")
    if chemin.stat().st_size == 0:
        raise ValueError(FICHIER_ILLISIBLE)

    if extension in TYPES_IMAGE:
        donnees = chemin.read_bytes()
        if extension in _IMAGES_DECODABLES:
            try:
                pymupdf.Pixmap(donnees)  # contrôle de décodage seulement
            except _ERREURS_LECTURE:
                raise ValueError(FICHIER_ILLISIBLE) from None
        return Plan(chemin, [Image(donnees, TYPES_IMAGE[extension])], "")

    images: list[Image] = []
    textes: list[str] = []
    try:
        with pymupdf.open(chemin) as document:
            for page in list(document)[:pages_max]:
                images.append(Image(page.get_pixmap(dpi=dpi).tobytes("png"), "image/png"))
                textes.append(page.get_text().strip())
    except _ERREURS_LECTURE:
        raise ValueError(FICHIER_ILLISIBLE) from None
    if not images:
        raise ValueError(FICHIER_ILLISIBLE)
    return Plan(chemin, images, "\n\n".join(t for t in textes if t))
