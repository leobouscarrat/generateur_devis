"""Tirage aléatoire d'une pièce de tôlerie réaliste, et sa géométrie.

Une pièce est décrite par une `SpecPiece` : profil de pliage (ailes et virages à 90°),
largeur, trous, coins, matière, traitement, notes… La même description sert :
- à dessiner le plan (dessin.py) ;
- à produire la bonne réponse au format de la pièce (verite.py).

Conventions géométriques :
- le profil est dessiné dans le plan (x, z) de la vue de côté, la pièce est extrudée sur
  la largeur (axe y) ;
- `ailes` contient les longueurs sur la fibre moyenne ; le plan et la bonne réponse les
  cotent à l'extérieur (voir `longueurs_exterieures`) ;
- seuls les plis à 90° sont générés ; les trous et les coins ne sont placés que sur les
  ailes horizontales, visibles dans la vue de dessus.
"""

import math
import random
from dataclasses import dataclass, field

from shapely.geometry import LineString

# --- Tables de tirage ----------------------------------------------------------------------

# Désignation écrite sur le plan, famille, épaisseurs disponibles (mm).
MATIERES = [
    ("S235JR", "acier", [1.0, 1.5, 2.0, 3.0, 4.0, 5.0]),
    ("DC01", "acier", [0.8, 1.0, 1.5, 2.0, 2.5, 3.0]),
    ("S355MC", "acier", [2.0, 3.0, 4.0, 5.0, 6.0]),
    ("Inox 304L", "inox", [1.0, 1.5, 2.0, 3.0]),
    ("X2CrNiMo17-12-2 (316L)", "inox", [1.0, 1.5, 2.0]),
    ("AlMg3 (5754 H111)", "aluminium", [1.0, 1.5, 2.0, 3.0, 4.0]),
]

# (texte FR, texte EN, type, familles compatibles)
TRAITEMENTS = [
    ("Zingage blanc", "White zinc plating", "zingage", {"acier"}),
    (
        "Peinture poudre RAL 9005",
        "Powder coating RAL 9005",
        "thermolaquage",
        {"acier", "aluminium"},
    ),
    ("Peinture époxy RAL 7035", "Epoxy paint RAL 7035", "peinture", {"acier", "aluminium"}),
    ("Cataphorèse noire", "Black e-coating", "cataphorese", {"acier"}),
    ("Galvanisation à chaud", "Hot-dip galvanizing", "galvanisation", {"acier"}),
    ("Passivation", "Passivation", "passivation", {"inox"}),
    ("Anodisation naturelle", "Clear anodizing", "anodisation", {"aluminium"}),
    ("Brut", "None", "aucun", {"acier", "inox", "aluminium"}),
]
TRAITEMENTS_PEINTS = {"thermolaquage", "peinture", "cataphorese"}

DESIGNATIONS = [
    ("SUPPORT", "BRACKET"),
    ("EQUERRE", "ANGLE BRACKET"),
    ("PATTE DE FIXATION", "MOUNTING TAB"),
    ("PLATINE", "PLATE"),
    ("CAPOT", "COVER"),
    ("RENFORT", "STIFFENER"),
    ("CHAPE", "CLEVIS"),
]

# Forme : cap de départ (degrés) et virages (+1 = à gauche / « haut », -1 = à droite / « bas »).
FORMES = {
    "plaque": (0, []),
    "L": (0, [1]),
    "Z": (0, [1, -1]),
    "U": (-90, [1, 1]),
    "chapeau": (0, [1, -1, -1, 1]),
}
POIDS_FORMES = {"plaque": 2, "L": 3, "Z": 2, "U": 2, "chapeau": 1}

DIAMETRES_TROUS = [4.5, 5.5, 6.5, 8.5, 10.5, 13.0]
# Composants à sertir : (type, filetage, diamètre de perçage, désignation FR, désignation EN)
COMPOSANTS = [
    ("ecrou_a_sertir", "M4", 5.4, "ÉCROU À SERTIR M4", "CLINCH NUT M4"),
    ("ecrou_a_sertir", "M5", 7.2, "ÉCROU À SERTIR M5", "CLINCH NUT M5"),
    ("ecrou_a_sertir", "M6", 8.75, "ÉCROU À SERTIR M6", "CLINCH NUT M6"),
    ("goujon_a_sertir", "M5", 5.4, "GOUJON À SERTIR M5x12", "CLINCH STUD M5x12"),
    ("goujon_a_sertir", "M6", 6.4, "GOUJON À SERTIR M6x16", "CLINCH STUD M6x16"),
]
NORMES_SERTISSAGE = ["NF E 27-130", "SPEC. AS-204", "STD 39.02.409"]

NOTES_OPERATIONS = [
    ("ÉBAVURER TOUTES LES ARÊTES", "DEBURR ALL EDGES"),
    ("CASSER LES ANGLES VIFS", "BREAK ALL SHARP EDGES"),
    ("MARQUER LA RÉFÉRENCE PAR MICRO-PERCUSSION", "MARK PART NUMBER BY DOT PEEN"),
    ("CONTRÔLE DIMENSIONNEL À 100 %", "100% DIMENSIONAL INSPECTION"),
]
NOTES_GENERALES = [
    ("RAYONS NON COTÉS : R1", "UNDIMENSIONED RADII: R1"),
    ("NE PAS MESURER SUR LE PLAN", "DO NOT SCALE DRAWING"),
]


# --- Description d'une pièce ---------------------------------------------------------------


@dataclass
class GroupeTrous:
    segment: int
    xs: list[float]
    ys: list[float]
    diametre: float
    tolerance: str | None = None
    composant: int | None = None
    """Indice dans COMPOSANTS si les trous reçoivent un composant à sertir."""

    @property
    def quantite(self) -> int:
        return len(self.xs) * len(self.ys)


@dataclass
class Coin:
    extremite: str  # « gauche » ou « droite »
    type: str  # « chanfrein » ou « rayon »
    taille: float


@dataclass
class Note:
    texte: str
    categorie: str
    dans_verite: bool = True
    """Faux pour les notes dont l'information a son propre champ (traitement, tolérance…)."""


@dataclass
class SpecPiece:
    identifiant: str
    langue: str
    virgule: bool
    police: str
    reference: str
    designation: str
    indice: str
    matiere: str | None
    famille: str
    epaisseur: float
    forme: str
    cap: float
    virages: list[int]
    ailes: list[float]
    largeur: float
    rayon: float
    rayon_en_note: bool
    trous: list[GroupeTrous] = field(default_factory=list)
    coins: list[Coin] = field(default_factory=list)
    traitement: tuple[str, str] | None = None  # (texte écrit, type)
    traitement_dans_cartouche: bool = True
    epargne: str | None = None
    tolerance_generale: str | None = None
    tolerance_dans_cartouche: bool = True
    composant: int | None = None
    quantite_composant: int = 0
    norme_sertissage: str | None = None
    notes: list[Note] = field(default_factory=list)
    erreur: str | None = None
    """Erreur volontaire (plans du niveau E), voir ERREURS."""
    erreur_detail: dict = field(default_factory=dict)

    def t(self, fr: str, en: str) -> str:
        return fr if self.langue == "fr" else en


# --- Géométrie -----------------------------------------------------------------------------


@dataclass
class Geometrie:
    points: list[tuple[float, float]]
    """Points de la fibre moyenne du profil (vue de côté), décalés pour commencer à x = z = 0."""
    contour: list[tuple[float, float]]
    """Contour extérieur du profil épaissi (vue de côté)."""
    longueur: float
    hauteur: float
    caps: list[float]
    """Cap de chaque aile, en degrés."""

    def horizontale(self, i: int) -> bool:
        return round(math.cos(math.radians(self.caps[i]))) != 0

    def x_aile(self, i: int) -> tuple[float, float]:
        (x1, _), (x2, _) = self.points[i], self.points[i + 1]
        return min(x1, x2), max(x1, x2)


def geometrie(spec: SpecPiece) -> Geometrie:
    caps, cap = [], spec.cap
    points = [(0.0, 0.0)]
    for i, longueur in enumerate(spec.ailes):
        caps.append(cap)
        x, z = points[-1]
        points.append(
            (x + longueur * math.cos(math.radians(cap)), z + longueur * math.sin(math.radians(cap)))
        )
        if i < len(spec.virages):
            cap += 90 * spec.virages[i]
    epais = LineString(points).buffer(spec.epaisseur / 2, cap_style="flat", join_style="mitre")
    xmin, zmin, xmax, zmax = epais.bounds
    decale = [(round(x - xmin, 6), round(z - zmin, 6)) for x, z in points]
    contour = [(x - xmin, z - zmin) for x, z in epais.exterior.coords]
    return Geometrie(decale, contour, round(xmax - xmin, 3), round(zmax - zmin, 3), caps)


def longueurs_exterieures(spec: SpecPiece) -> list[float]:
    """Longueur de chaque aile cotée à l'extérieur : + une demi-épaisseur par pli adjacent."""
    dernier = len(spec.ailes) - 1
    return [
        round(longueur + spec.epaisseur / 2 * ((i > 0) + (i < dernier)), 3)
        for i, longueur in enumerate(spec.ailes)
    ]


# --- Tirage --------------------------------------------------------------------------------


def _arrondi(valeur: float, pas: float = 0.5) -> float:
    return round(round(valeur / pas) * pas, 3)


def _tirer_trous(rng: random.Random, spec: SpecPiece, geo: Geometrie) -> None:
    """Place 0 à 2 groupes de trous sur les ailes horizontales, loin des plis et des bords."""
    groupes_max = rng.choice([0, 1, 1, 2, 2])
    if spec.composant is not None:
        groupes_max = max(groupes_max, 1)
    composant_place = spec.composant is None
    ailes = [i for i in range(len(spec.ailes)) if geo.horizontale(i)]
    rng.shuffle(ailes)
    for i in ailes:
        if len(spec.trous) >= groupes_max:
            break
        if not composant_place:
            diametre = COMPOSANTS[spec.composant][2]
        else:
            diametre = rng.choice(DIAMETRES_TROUS)
        x1, x2 = geo.x_aile(i)
        dernier = len(spec.ailes) - 1
        marge_pli = 2 * spec.epaisseur + spec.rayon + diametre / 2 + 2
        marge_bord = max(diametre, 1.5 * spec.epaisseur) + diametre / 2 + 8
        debut = x1 + (marge_bord if i == 0 else marge_pli)
        fin = x2 - (marge_bord if i == dernier else marge_pli)
        if fin - debut < 2:
            continue
        marge_y = marge_bord
        if spec.largeur - 2 * marge_y < 0:
            continue
        colonnes = 2 if fin - debut > 30 and rng.random() < 0.4 else 1
        lignes = 2 if spec.largeur - 2 * marge_y > 20 and rng.random() < 0.6 else 1
        if colonnes == 1:
            xs = [_arrondi(rng.uniform(debut, fin))]
        else:
            xs = [_arrondi(debut + (fin - debut) * 0.2), _arrondi(debut + (fin - debut) * 0.8)]
        if lignes == 1:
            ys = [_arrondi(spec.largeur / 2)]
        else:
            ecart = _arrondi(rng.uniform(marge_y, spec.largeur / 2 - 5))
            ys = [ecart, _arrondi(spec.largeur - ecart)]
        groupe = GroupeTrous(i, xs, ys, diametre)
        if not composant_place:
            groupe.composant = spec.composant
            spec.quantite_composant = groupe.quantite
            composant_place = True
        elif rng.random() < 0.25:
            tolerance = rng.choice(["+0,1/0", "H11", "±0,1"])
            groupe.tolerance = tolerance if spec.virgule else tolerance.replace(",", ".")
        spec.trous.append(groupe)
    if not composant_place:  # aucune aile assez grande : pas de composant
        spec.composant = None


def _tirer_coins(rng: random.Random, spec: SpecPiece, geo: Geometrie) -> None:
    extremites = []
    if geo.horizontale(0):
        extremites.append(("gauche", spec.ailes[0]))
    if len(spec.ailes) > 1 and geo.horizontale(len(spec.ailes) - 1):
        extremites.append(("droite", spec.ailes[-1]))
    if spec.forme == "plaque":
        extremites = [("gauche", spec.ailes[0]), ("droite", spec.ailes[0])]
    type_commun = rng.choice(["chanfrein", "rayon"])
    for extremite, longueur in extremites:
        if rng.random() < 0.45:
            continue
        limite = min(spec.largeur / 3, longueur / 3)
        tailles = [
            t
            for t in (
                [3.0, 5.0, 10.0, 15.0] if type_commun == "chanfrein" else [2.0, 3.0, 5.0, 10.0]
            )
            if t <= limite
        ]
        if tailles:
            spec.coins.append(Coin(extremite, type_commun, rng.choice(tailles)))


def tirer_piece(rng: random.Random, identifiant: str) -> tuple[SpecPiece, Geometrie]:
    langue = rng.choice(["fr", "fr", "en"])
    matiere, famille, epaisseurs = rng.choice(MATIERES)
    epaisseur = rng.choice(epaisseurs)
    forme = rng.choices(list(POIDS_FORMES), weights=list(POIDS_FORMES.values()))[0]
    cap, virages = FORMES[forme]
    rayon = rng.choice([epaisseur, 1.5 * epaisseur, 2 * epaisseur])
    aile_min = max(12.0, 4 * epaisseur + rayon)
    if forme == "plaque":
        ailes = [_arrondi(rng.uniform(40, 300), 1)]
    else:
        ailes = [_arrondi(rng.uniform(aile_min, 120), 1) for _ in range(len(virages) + 1)]
    designation_fr, designation_en = rng.choice(DESIGNATIONS)

    spec = SpecPiece(
        identifiant=identifiant,
        langue=langue,
        virgule=langue == "fr" or rng.random() < 0.2,
        police=rng.choice(["DejaVu Sans", "Liberation Sans", "DejaVu Serif", "DejaVu Sans Mono"]),
        reference=f"{rng.choice(['SUP', 'TOL', 'PF', 'MEC'])}-{rng.randint(1000, 9999)}",
        designation=designation_fr if langue == "fr" else designation_en,
        indice=rng.choice("ABCD"),
        matiere=None if rng.random() < 0.1 else matiere,
        famille=famille,
        epaisseur=epaisseur,
        forme=forme,
        cap=cap,
        virages=list(virages),
        ailes=ailes,
        largeur=_arrondi(rng.uniform(25, 200), 1),
        rayon=rayon,
        rayon_en_note=bool(virages) and rng.random() < 0.85,
    )
    if rng.random() < 0.35:
        spec.composant = rng.randrange(len(COMPOSANTS))

    geo = geometrie(spec)
    _tirer_trous(rng, spec, geo)
    _tirer_coins(rng, spec, geo)

    # Traitement : dans le cartouche, en note, ou absent.
    if rng.random() < 0.85:
        compatibles = [t for t in TRAITEMENTS if famille in t[3]]
        fr, en, type_traitement, _ = rng.choice(compatibles)
        spec.traitement = (spec.t(fr, en), type_traitement)
        spec.traitement_dans_cartouche = rng.random() < 0.7
        if not spec.traitement_dans_cartouche:
            spec.notes.append(
                Note(
                    spec.t(f"TRAITEMENT : {fr.upper()}", f"FINISH: {en.upper()}"),
                    "traitement",
                    False,
                )
            )
        if type_traitement in TRAITEMENTS_PEINTS and spec.composant is not None:
            spec.epargne = spec.t("FILETAGES", "THREADS")
            spec.notes.append(
                Note(
                    spec.t("ÉPARGNE PEINTURE DES FILETAGES", "NO PAINT ON THREADS"),
                    "traitement",
                    False,
                )
            )

    # Tolérance générale : dans le cartouche, en note, ou absente.
    if rng.random() < 0.85:
        spec.tolerance_generale = f"ISO 2768-{rng.choice('fmc')}"
        spec.tolerance_dans_cartouche = rng.random() < 0.6
        if not spec.tolerance_dans_cartouche:
            spec.notes.append(
                Note(
                    spec.t(
                        f"TOLÉRANCES GÉNÉRALES : {spec.tolerance_generale}",
                        f"GENERAL TOLERANCES: {spec.tolerance_generale}",
                    ),
                    "tolerance",
                    False,
                )
            )

    if spec.rayon_en_note:
        r = f"{spec.rayon:g}".replace(".", "," if spec.virgule else ".")
        spec.notes.insert(
            0,
            Note(
                spec.t(f"RAYON DE PLIAGE INTÉRIEUR : {r} mm", f"INSIDE BEND RADIUS: {r} mm"),
                "pliage",
            ),
        )
    if spec.composant is not None:
        spec.norme_sertissage = rng.choice(NORMES_SERTISSAGE)
        spec.notes.append(
            Note(
                spec.t(
                    f"SERTISSAGE SELON {spec.norme_sertissage}",
                    f"CLINCH PER {spec.norme_sertissage}",
                ),
                "assemblage",
            )
        )
    for fr, en in rng.sample(NOTES_OPERATIONS, rng.randint(0, 2)):
        spec.notes.append(Note(spec.t(fr, en), "operation"))
    for fr, en in rng.sample(NOTES_GENERALES, rng.randint(0, 1)):
        spec.notes.append(Note(spec.t(fr, en), "general"))
    rng.shuffle(spec.notes)
    return spec, geo


# --- Plans volontairement erronés (niveau E) -------------------------------------------------

ERREURS = {
    "matiere_absente": "Matière non indiquée (cartouche « — »)",
    "epaisseur_absente": "Épaisseur non indiquée (cartouche « — »)",
    "cote_aile_absente": "Longueur d'une aile non cotée, sans cote d'encombrement pour la retrouver",
    "cotes_contradictoires": "Cote d'encombrement différente de la somme des ailes",
}


def tirer_piece_erronee(
    rng: random.Random, identifiant: str, type_erreur: str
) -> tuple[SpecPiece, Geometrie]:
    """Tire une pièce puis y introduit une erreur de type `type_erreur`."""
    while True:
        spec, geo = tirer_piece(rng, identifiant)
        # Les erreurs de cotes demandent au moins deux ailes (une pièce pliée).
        if type_erreur in ("matiere_absente", "epaisseur_absente") or len(spec.ailes) >= 2:
            break
    spec.erreur = type_erreur
    if type_erreur == "matiere_absente":
        spec.matiere = None
    elif type_erreur == "cote_aile_absente":
        spec.erreur_detail = {"aile": rng.randrange(len(spec.ailes))}
    elif type_erreur == "cotes_contradictoires":
        spec.erreur_detail = {"ecart": rng.choice([-1, 1]) * rng.choice([5, 8, 10, 12, 15, 20])}
    elif type_erreur != "epaisseur_absente":
        raise ValueError(f"Erreur inconnue : {type_erreur}")
    return spec, geo
