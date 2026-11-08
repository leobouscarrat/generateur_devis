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


def charger_plan(chemin: Path | str, dpi: int = 150, pages_max: int = 2) -> Plan:
    chemin = Path(chemin)
    extension = chemin.suffix.lower()
    if extension in TYPES_IMAGE:
        return Plan(chemin, [Image(chemin.read_bytes(), TYPES_IMAGE[extension])], "")
    if extension != ".pdf":
        raise ValueError(f"Format non supporté : {extension} (PDF, PNG, JPG ou WEBP)")

    images: list[Image] = []
    textes: list[str] = []
    with pymupdf.open(chemin) as document:
        for page in list(document)[:pages_max]:
            images.append(Image(page.get_pixmap(dpi=dpi).tobytes("png"), "image/png"))
            textes.append(page.get_text().strip())
    return Plan(chemin, images, "\n\n".join(t for t in textes if t))
