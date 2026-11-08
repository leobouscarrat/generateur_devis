"""Mise en plan d'une pièce générée : PDF vectoriel avec vues, cotes, notes et cartouche.

Les coordonnées de dessin sont en millimètres « papier » (origine en bas à gauche).
Chaque cote écrite sur le plan est enregistrée au moment où elle est dessinée : la liste des
cotes de la bonne réponse correspond donc exactement à ce qui est imprimé.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402

from generateur_devis.generateur.modele import (  # noqa: E402
    COMPOSANTS,
    Geometrie,
    SpecPiece,
    longueurs_exterieures,
)
from generateur_devis.schema import Cote  # noqa: E402

FORMATS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}
ECHELLES = [5.0, 2.0, 1.0, 0.5, 0.2, 0.1]
LARGEUR_COLONNE = 125.0  # colonne de droite : notes, nomenclature, cartouche
TRAIT_FIN, TRAIT_MOYEN, TRAIT_FORT = 0.25, 0.45, 0.8


class Feuille:
    def __init__(self, spec: SpecPiece, largeur: float, hauteur: float):
        self.spec = spec
        self.largeur, self.hauteur = largeur, hauteur
        self.fig = plt.figure(figsize=(largeur / 25.4, hauteur / 25.4))
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, largeur)
        self.ax.set_ylim(0, hauteur)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.cotes: list[Cote] = []

    # --- primitives ---

    def nombre(self, valeur: float) -> str:
        texte = f"{valeur:.2f}".rstrip("0").rstrip(".")
        return texte.replace(".", ",") if self.spec.virgule else texte

    def texte(self, x, y, s, taille=7.0, **options):
        self.ax.text(x, y, s, fontsize=taille, fontfamily=self.spec.police, **options)

    def ligne(self, points, epaisseur=TRAIT_MOYEN, style="-"):
        xs, ys = zip(*points, strict=True)
        self.ax.plot(xs, ys, color="black", lw=epaisseur, ls=style, solid_capstyle="butt")

    def cote(self, p1, p2, decalage, valeur, type_cote="lineaire"):
        """Cote linéaire entre p1 et p2, décalée perpendiculairement de `decalage` mm."""
        (x1, y1), (x2, y2) = p1, p2
        longueur = math.hypot(x2 - x1, y2 - y1)
        if longueur < 1e-6:
            return
        ux, uy = (x2 - x1) / longueur, (y2 - y1) / longueur
        nx, ny = -uy, ux
        sens = 1 if decalage >= 0 else -1
        q1 = (x1 + nx * decalage, y1 + ny * decalage)
        q2 = (x2 + nx * decalage, y2 + ny * decalage)
        for p, q in ((p1, q1), (p2, q2)):
            self.ligne(
                [
                    (p[0] + nx * sens, p[1] + ny * sens),
                    (q[0] + nx * sens * 1.5, q[1] + ny * sens * 1.5),
                ],
                TRAIT_FIN,
            )
        self.ax.annotate(
            "",
            xy=q1,
            xytext=q2,
            arrowprops={
                "arrowstyle": "<|-|>",
                "lw": TRAIT_FIN,
                "shrinkA": 0,
                "shrinkB": 0,
                "mutation_scale": 5,
                "color": "black",
            },
        )
        angle = math.degrees(math.atan2(uy, ux))
        if angle > 90:
            angle -= 180
        elif angle <= -90:
            angle += 180
        milieu = ((q1[0] + q2[0]) / 2 + nx * sens * 2.2, (q1[1] + q2[1]) / 2 + ny * sens * 2.2)
        texte = self.nombre(valeur)
        self.texte(*milieu, texte, rotation=angle, ha="center", va="center", rotation_mode="anchor")
        self.cotes.append(Cote(valeur=valeur, type=type_cote, texte=texte))

    def rappel(self, point, position, texte, cote: Cote):
        """Annotation avec ligne de rappel (perçages, chanfreins, rayons)."""
        self.ax.annotate(
            texte,
            xy=point,
            xytext=position,
            fontsize=7,
            fontfamily=self.spec.police,
            ha="left",
            va="center",
            arrowprops={
                "arrowstyle": "-|>",
                "lw": TRAIT_FIN,
                "mutation_scale": 5,
                "color": "black",
                "shrinkA": 1,
            },
        )
        cote.texte = texte
        self.cotes.append(cote)


# --- Vues --------------------------------------------------------------------------------


def _contour_dessus(spec: SpecPiece, longueur: float) -> list[tuple[float, float]]:
    """Contour vu de dessus (rectangle longueur × largeur) avec chanfreins et rayons de coin."""
    largeur = spec.largeur
    modifs = {c.extremite: c for c in spec.coins}
    coins = [
        ((0, 0), "gauche", (1, 0), (0, 1)),
        ((longueur, 0), "droite", (0, 1), (-1, 0)),
        ((longueur, largeur), "droite", (-1, 0), (0, -1)),
        ((0, largeur), "gauche", (0, -1), (1, 0)),
    ]
    points = []
    # Pour chaque coin : direction vers le coin suivant, puis vers le coin précédent.
    for (cx, cy), extremite, suivant, precedent in coins:
        coin = modifs.get(extremite)
        if coin is None:
            points.append((cx, cy))
            continue
        t = coin.taille
        # Le coin est remplacé par un point sur chaque arête, à la distance t du coin.
        arrivee = (cx + precedent[0] * t, cy + precedent[1] * t)
        depart = (cx + suivant[0] * t, cy + suivant[1] * t)
        if coin.type == "chanfrein":
            points += [arrivee, depart]
        else:
            centre = (cx + (precedent[0] + suivant[0]) * t, cy + (precedent[1] + suivant[1]) * t)
            a0 = math.atan2(arrivee[1] - centre[1], arrivee[0] - centre[0])
            a1 = math.atan2(depart[1] - centre[1], depart[0] - centre[0])
            delta = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            points += [
                (
                    centre[0] + t * math.cos(a0 + delta * k / 8),
                    centre[1] + t * math.sin(a0 + delta * k / 8),
                )
                for k in range(9)
            ]
    return points


def _vue_dessus(f: Feuille, geo: Geometrie, ox: float, oy: float, e: float) -> None:
    spec = f.spec
    P = lambda x, y: (ox + x * e, oy + y * e)  # noqa: E731
    f.ax.add_patch(
        Polygon(
            [P(x, y) for x, y in _contour_dessus(spec, geo.longueur)],
            closed=True,
            fill=False,
            lw=TRAIT_FORT,
        )
    )
    # Arêtes des ailes verticales (lignes de pli visibles).
    for i in range(len(spec.ailes)):
        if not geo.horizontale(i):
            x = geo.points[i][0]
            for bord in (x - spec.epaisseur / 2, x + spec.epaisseur / 2):
                if 0 < bord < geo.longueur:
                    f.ligne([P(bord, 0), P(bord, spec.largeur)], TRAIT_MOYEN)

    # Trous, axes, cotes de position et rappels.
    niveau = 0
    for groupe in spec.trous:
        for x in groupe.xs:
            for y in groupe.ys:
                f.ax.add_patch(Circle(P(x, y), groupe.diametre / 2 * e, fill=False, lw=TRAIT_MOYEN))
                r = groupe.diametre / 2 * e + 1.5
                f.ligne(
                    [(P(x, y)[0] - r, P(x, y)[1]), (P(x, y)[0] + r, P(x, y)[1])], TRAIT_FIN, "-."
                )
                f.ligne(
                    [(P(x, y)[0], P(x, y)[1] - r), (P(x, y)[0], P(x, y)[1] + r)], TRAIT_FIN, "-."
                )
        x0, y0 = groupe.xs[0], groupe.ys[0]
        f.cote(P(0, 0), P(x0, 0), -(8 + 7 * niveau), x0)
        f.cote(P(0, 0), P(0, y0), 8 + 7 * niveau, y0)
        niveau += 1
        diametre = f.nombre(groupe.diametre)
        texte = f"{groupe.quantite}x Ø{diametre}" if groupe.quantite > 1 else f"Ø{diametre}"
        if groupe.tolerance:
            texte += f" {groupe.tolerance}"
        xh, yh = groupe.xs[-1], groupe.ys[-1]
        bord = (
            P(xh, yh)[0] + groupe.diametre / 2 * e * 0.7,
            P(xh, yh)[1] + groupe.diametre / 2 * e * 0.7,
        )
        # Texte au-dessus de la vue, à droite, pour ne pas chevaucher les cotes.
        position = (P(geo.longueur, 0)[0] + 6, P(0, spec.largeur)[1] + 8 + 7 * (niveau - 1))
        f.rappel(
            bord,
            position,
            texte,
            Cote(
                valeur=groupe.diametre,
                type="diametre",
                quantite=groupe.quantite,
                tolerance=groupe.tolerance,
            ),
        )

    # Largeur.
    f.cote(P(geo.longueur, 0), P(geo.longueur, spec.largeur), -10, spec.largeur)

    # Rappels de coins : un par taille différente.
    tailles: dict[tuple[str, float], list[str]] = {}
    for coin in spec.coins:
        tailles.setdefault((coin.type, coin.taille), []).append(coin.extremite)
    for (type_coin, taille), extremites in tailles.items():
        x = 0 if extremites[0] == "gauche" else geo.longueur
        sens = 1 if x == 0 else -1
        point = P(x + sens * taille / 2, spec.largeur - taille / 2)
        quantite = 2 * len(extremites)
        valeur = f.nombre(taille)
        texte = (
            f"{quantite}x {valeur}x{valeur}"
            if type_coin == "chanfrein"
            else f"{quantite}x R{valeur}"
        )
        f.rappel(
            point,
            (point[0] - sens * 4 - (22 if sens < 0 else 0), point[1] + 10),
            texte,
            Cote(
                valeur=taille,
                type="chanfrein" if type_coin == "chanfrein" else "rayon",
                quantite=quantite,
            ),
        )


def _vue_cote(f: Feuille, geo: Geometrie, ox: float, oy: float, e: float) -> None:
    spec = f.spec
    P = lambda x, z: (ox + x * e, oy + z * e)  # noqa: E731
    f.ax.add_patch(
        Polygon([P(x, z) for x, z in geo.contour], closed=True, fill=False, lw=TRAIT_FORT)
    )
    cx = sum(x for x, _ in geo.contour) / len(geo.contour)
    cz = sum(z for _, z in geo.contour) / len(geo.contour)
    if spec.forme == "plaque":
        f.cote(P(0, 0), P(geo.longueur, 0), -8, spec.ailes[0])
        return
    # Une cote par aile, cotée à l'extérieur (comme sur un vrai plan de tôlerie).
    cotes_ailes = longueurs_exterieures(spec)
    dernier = len(spec.ailes) - 1
    aile_absente = spec.erreur_detail.get("aile") if spec.erreur == "cote_aile_absente" else None
    for i, longueur in enumerate(cotes_ailes):
        if i == aile_absente:
            continue
        (x1, z1), (x2, z2) = geo.points[i], geo.points[i + 1]
        ux, uz = (x2 - x1) / spec.ailes[i], (z2 - z1) / spec.ailes[i]
        # Prolonge la cote d'une demi-épaisseur du côté de chaque pli (face extérieure).
        if i > 0:
            x1, z1 = x1 - ux * spec.epaisseur / 2, z1 - uz * spec.epaisseur / 2
        if i < dernier:
            x2, z2 = x2 + ux * spec.epaisseur / 2, z2 + uz * spec.epaisseur / 2
        mx, mz = (x1 + x2) / 2, (z1 + z2) / 2
        nx, nz = -uz, ux  # normale à gauche du sens de parcours
        exterieur = (mx + nx - cx) ** 2 + (mz + nz - cz) ** 2 > (mx - cx) ** 2 + (mz - cz) ** 2
        f.cote(P(x1, z1), P(x2, z2), 7 if exterieur else -7, longueur)
    if spec.erreur == "cote_aile_absente":
        return  # pas d'encombrement : la longueur manquante ne peut pas être retrouvée
    if spec.erreur == "cotes_contradictoires":
        # Encombrement faux, toujours affiché : contredit la somme des ailes.
        f.cote(P(0, 0), P(geo.longueur, 0), -16, geo.longueur + spec.erreur_detail["ecart"])
        if not any(abs(geo.hauteur - c) < 1e-6 for c in cotes_ailes):
            f.cote(P(0, 0), P(0, geo.hauteur), 16, geo.hauteur)
        return
    # Encombrement, seulement s'il n'est pas déjà donné par une cote d'aile.
    if not any(abs(geo.longueur - c) < 1e-6 for c in cotes_ailes):
        f.cote(P(0, 0), P(geo.longueur, 0), -16, geo.longueur)
    if not any(abs(geo.hauteur - c) < 1e-6 for c in cotes_ailes):
        f.cote(P(0, 0), P(0, geo.hauteur), 16, geo.hauteur)


# --- Cartouche, notes, nomenclature ------------------------------------------------------


def _cartouche(f: Feuille, echelle: float) -> None:
    spec = f.spec
    t = spec.t
    lignes = [
        (t("Désignation", "Title"), spec.designation),
        (t("Référence", "Part number"), spec.reference),
        (t("Indice", "Revision"), spec.indice),
        (t("Matière", "Material"), spec.matiere or "—"),
        (
            t("Épaisseur", "Thickness"),
            "—" if spec.erreur == "epaisseur_absente" else f"{f.nombre(spec.epaisseur)} mm",
        ),
    ]
    if spec.traitement and spec.traitement_dans_cartouche:
        lignes.append((t("Traitement", "Finish"), spec.traitement[0]))
    if spec.tolerance_generale and spec.tolerance_dans_cartouche:
        lignes.append((t("Tolérances générales", "General tolerances"), spec.tolerance_generale))
    lignes.append((t("Unités", "Units"), "mm"))
    echelle_txt = f"{f.nombre(echelle)}:1" if echelle >= 1 else f"1:{f.nombre(1 / echelle)}"
    lignes.append((t("Échelle", "Scale"), echelle_txt))

    x0, x1 = f.largeur - 10 - LARGEUR_COLONNE + 5, f.largeur - 10
    hauteur_ligne = 6.5
    y = 10
    for libelle, valeur in reversed(lignes):
        f.ax.add_patch(Rectangle((x0, y), x1 - x0, hauteur_ligne, fill=False, lw=TRAIT_MOYEN))
        f.ligne([(x0 + 38, y), (x0 + 38, y + hauteur_ligne)], TRAIT_FIN)
        f.texte(x0 + 1.5, y + hauteur_ligne / 2, libelle, 6, va="center")
        f.texte(x0 + 40, y + hauteur_ligne / 2, valeur, 7.5, va="center", fontweight="bold")
        y += hauteur_ligne
    f.y_haut_cartouche = y


def _nomenclature(f: Feuille) -> None:
    spec = f.spec
    if spec.composant is None:
        return
    t = spec.t
    _, _, _, designation_fr, designation_en = COMPOSANTS[spec.composant]
    lignes = [
        (t("REP.", "ITEM"), t("DÉSIGNATION", "DESCRIPTION"), t("QTÉ", "QTY")),
        ("1", spec.designation, "1"),
        ("2", t(designation_fr, designation_en), str(spec.quantite_composant)),
    ]
    x0, x1 = f.largeur - 10 - LARGEUR_COLONNE + 5, f.largeur - 10
    y = f.y_haut_cartouche + 6
    for rep, designation, quantite in reversed(lignes):
        f.ax.add_patch(Rectangle((x0, y), x1 - x0, 6, fill=False, lw=TRAIT_MOYEN))
        f.ligne([(x0 + 14, y), (x0 + 14, y + 6)], TRAIT_FIN)
        f.ligne([(x1 - 16, y), (x1 - 16, y + 6)], TRAIT_FIN)
        f.texte(x0 + 7, y + 3, rep, 6.5, ha="center", va="center")
        f.texte(x0 + 16, y + 3, designation, 6.5, va="center")
        f.texte(x1 - 8, y + 3, quantite, 6.5, ha="center", va="center")
        y += 6


def _notes(f: Feuille) -> None:
    spec = f.spec
    if not spec.notes:
        return
    x = f.largeur - 10 - LARGEUR_COLONNE + 5
    y = f.hauteur - 20
    f.texte(x, y, "NOTES :" if spec.langue == "fr" else "NOTES:", 8, fontweight="bold")
    for i, note in enumerate(spec.notes, start=1):
        y -= 5.5
        f.texte(x + 2, y, f"{i}. {note.texte}", 6.5)


# --- Plan complet ------------------------------------------------------------------------


def _mise_en_page(geo: Geometrie, spec: SpecPiece) -> tuple[str, float]:
    for format_papier in ("A4", "A3"):
        largeur, hauteur = FORMATS[format_papier]
        zone_l = largeur - LARGEUR_COLONNE - 50
        zone_h = hauteur - 40
        for echelle in ECHELLES:
            besoin_l = geo.longueur * echelle + 40
            besoin_h = (spec.largeur + geo.hauteur) * echelle + 85
            if (
                besoin_l <= zone_l
                and besoin_h <= zone_h
                and (format_papier == "A3" or echelle >= 0.5)
            ):
                return format_papier, echelle
    return "A3", ECHELLES[-1]


def dessiner(spec: SpecPiece, geo: Geometrie, chemin: Path) -> list[Cote]:
    """Dessine le plan en PDF et renvoie la liste des cotes imprimées."""
    format_papier, echelle = _mise_en_page(geo, spec)
    largeur, hauteur = FORMATS[format_papier]
    f = Feuille(spec, largeur, hauteur)
    f.ax.add_patch(Rectangle((10, 10), largeur - 20, hauteur - 20, fill=False, lw=TRAIT_FORT))

    ox = 45
    oy_cote = 40
    oy_dessus = oy_cote + geo.hauteur * echelle + 40
    _vue_cote(f, geo, ox, oy_cote, echelle)
    _vue_dessus(f, geo, ox, oy_dessus, echelle)
    _cartouche(f, echelle)
    _nomenclature(f)
    _notes(f)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    f.fig.savefig(chemin, format="pdf")
    plt.close(f.fig)
    return f.cotes
