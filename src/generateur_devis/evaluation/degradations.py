"""Dégradation des plans (voir docs/evaluation.md §5).

Niveaux :
- 0 : PDF propre, texte du PDF fourni avec l'image (situation idéale) ;
- 1 : image propre du PDF, sans texte ;
- 2 : scan (niveaux de gris, 100 – 150 dpi, rotation ±2°, flou, bruit, compression JPEG) ;
- 3 : photo (perspective, fond visible, éclairage inégal, flou, teinte, compression JPEG).

Les dégradations sont reproductibles : le tirage dépend de l'identifiant du plan.
"""

import io
import random

import numpy as np
import pymupdf
from PIL import Image as PILImage
from PIL import ImageFilter

from generateur_devis.extraction.documents import Plan
from generateur_devis.llm.base import Image

NIVEAUX = {0: "PDF propre", 1: "image propre", 2: "scan", 3: "photo"}


def _rendre(plan: Plan, dpi: int) -> PILImage.Image:
    with pymupdf.open(plan.chemin) as document:
        pixmap = document[0].get_pixmap(dpi=dpi)
    return PILImage.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")


def _jpeg(image: PILImage.Image, qualite: int) -> Image:
    tampon = io.BytesIO()
    image.save(tampon, format="JPEG", quality=qualite)
    return Image(tampon.getvalue(), "image/jpeg")


def scan(image: PILImage.Image, rng: random.Random, dpi_source: int) -> Image:
    gris = image.convert("L")
    gris = gris.rotate(rng.uniform(-2, 2), resample=PILImage.BICUBIC, expand=True, fillcolor=255)
    facteur = rng.uniform(100, 150) / dpi_source
    gris = gris.resize(
        (round(gris.width * facteur), round(gris.height * facteur)), PILImage.LANCZOS
    )
    gris = gris.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.7)))
    tableau = np.asarray(gris, dtype=np.float32)
    # Papier légèrement gris, encre moins noire, bruit du capteur et quelques poussières.
    tableau = 25 + tableau * rng.uniform(0.82, 0.9)
    gen = np.random.default_rng(rng.randrange(2**32))
    tableau += gen.normal(0, rng.uniform(5, 10), tableau.shape)
    poussieres = gen.random(tableau.shape) < 0.0004
    tableau[poussieres] = gen.uniform(40, 120, poussieres.sum())
    gris = PILImage.fromarray(np.clip(tableau, 0, 255).astype(np.uint8))
    return _jpeg(gris, rng.randint(55, 75))


def _coefficients_perspective(source, destination) -> list[float]:
    """Coefficients de PIL (image de sortie → image d'entrée) pour 4 points appariés."""
    lignes, valeurs = [], []
    for (xs, ys), (xd, yd) in zip(source, destination, strict=True):
        lignes.append([xd, yd, 1, 0, 0, 0, -xs * xd, -xs * yd])
        lignes.append([0, 0, 0, xd, yd, 1, -ys * xd, -ys * yd])
        valeurs += [xs, ys]
    return list(np.linalg.solve(np.array(lignes, float), np.array(valeurs, float)))


def photo(image: PILImage.Image, rng: random.Random) -> Image:
    largeur, hauteur = image.size
    marge = 0.12
    fond_l, fond_h = round(largeur * (1 + 2 * marge)), round(hauteur * (1 + 2 * marge))
    # Fond : table ou bureau, couleur uniforme bruitée.
    teinte = rng.choice([(120, 95, 70), (90, 90, 95), (160, 150, 135), (60, 60, 60)])
    gen = np.random.default_rng(rng.randrange(2**32))
    fond = np.ones((fond_h, fond_l, 3), np.float32) * np.array(teinte, np.float32)
    fond += gen.normal(0, 8, (fond_h, fond_l, 1))

    # Feuille vue en perspective : chaque coin est déplacé au hasard.
    dx, dy = largeur * 0.07, hauteur * 0.07
    x0, y0 = largeur * marge, hauteur * marge
    coins_dest = [
        (x0 + rng.uniform(-dx, dx), y0 + rng.uniform(-dy, dy)),
        (x0 + largeur + rng.uniform(-dx, dx), y0 + rng.uniform(-dy, dy)),
        (x0 + largeur + rng.uniform(-dx, dx), y0 + hauteur + rng.uniform(-dy, dy)),
        (x0 + rng.uniform(-dx, dx), y0 + hauteur + rng.uniform(-dy, dy)),
    ]
    coins_source = [(0, 0), (largeur, 0), (largeur, hauteur), (0, hauteur)]
    coefficients = _coefficients_perspective(coins_source, coins_dest)
    feuille = image.transform(
        (fond_l, fond_h), PILImage.PERSPECTIVE, coefficients, PILImage.BICUBIC, fillcolor=(0, 0, 0)
    )
    masque = PILImage.new("L", image.size, 255).transform(
        (fond_l, fond_h), PILImage.PERSPECTIVE, coefficients, PILImage.BILINEAR, fillcolor=0
    )
    alpha = np.asarray(masque, np.float32)[..., None] / 255
    papier = np.asarray(feuille, np.float32) * np.array([1.0, 0.97, 0.9], np.float32)
    tableau = papier * alpha + fond * (1 - alpha)

    # Éclairage inégal : dégradé dans une direction au hasard (ombre portée, lampe de côté).
    angle = rng.uniform(0, 2 * np.pi)
    yy, xx = np.mgrid[0:fond_h, 0:fond_l].astype(np.float32)
    projection = (xx / fond_l - 0.5) * np.cos(angle) + (yy / fond_h - 0.5) * np.sin(angle)
    lumiere = 1 - rng.uniform(0.2, 0.4) * (projection - projection.min()) / np.ptp(projection)
    tableau *= lumiere[..., None]
    tableau += gen.normal(0, 5, tableau.shape)

    resultat = PILImage.fromarray(np.clip(tableau, 0, 255).astype(np.uint8))
    resultat = resultat.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.5)))
    # Taille d'une photo de téléphone recadrée : ~2000 px sur le grand côté.
    facteur = 2000 / max(resultat.size)
    resultat = resultat.resize(
        (round(resultat.width * facteur), round(resultat.height * facteur)), PILImage.LANCZOS
    )
    return _jpeg(resultat, rng.randint(70, 85))


def degrader(plan: Plan, niveau: int, identifiant: str) -> Plan:
    """Plan au niveau de dégradation demandé (le niveau 0 renvoie le plan tel quel)."""
    if niveau == 0:
        return plan
    if plan.chemin.suffix.lower() != ".pdf":
        raise ValueError("Les dégradations s'appliquent aux plans PDF générés")
    rng = random.Random(f"degradation-{niveau}-{identifiant}")
    if niveau == 1:
        return Plan(plan.chemin, plan.images, "")
    if niveau == 2:
        dpi = 200
        return Plan(plan.chemin, [scan(_rendre(plan, dpi), rng, dpi)], "")
    if niveau == 3:
        return Plan(plan.chemin, [photo(_rendre(plan, 150), rng)], "")
    raise ValueError(f"Niveau inconnu : {niveau} ({NIVEAUX})")
