"""Format JSON d'une pièce lue sur un plan.

Ce format est partagé par :
- l'extraction : c'est ce que le modèle d'IA doit renvoyer ;
- le générateur de plans : c'est la bonne réponse de chaque plan généré ;
- la conversion des jeux publics (cadsy, ecado) ;
- la comparaison champ par champ de l'évaluation ;
- plus tard, l'outil de devis.

Conventions :
- les valeurs sont recopiées telles qu'elles figurent sur le plan, dans l'unité du plan
  (`unites`). Les conversions et les calculs sont faits par le code, jamais par l'IA ;
- une information absente du plan vaut `null` : elle ne doit jamais être devinée ;
- `confiance` et `source` sont remplis par l'IA, et laissés vides dans les bonnes réponses.

Les descriptions des champs sont transmises au modèle avec le schéma JSON : elles font
partie des instructions d'extraction.
"""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

VERSION_SCHEMA = "1.2"

T = TypeVar("T")

Unite = Literal["mm", "in"]
FamilleMatiere = Literal["acier", "inox", "aluminium", "cuivre", "laiton", "titane", "autre"]
TypeTraitement = Literal[
    "aucun",
    "peinture",
    "thermolaquage",
    "cataphorese",
    "zingage",
    "galvanisation",
    "anodisation",
    "passivation",
    "autre",
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Base):
    """Endroit du plan où l'information a été lue."""

    page: int = Field(1, ge=1, description="Numéro de page, à partir de 1.")
    zone: tuple[float, float, float, float] | None = Field(
        None,
        description=(
            "Zone [x, y, largeur, hauteur] en fraction de la page (de 0 à 1), "
            "origine en haut à gauche."
        ),
    )


class _Trace(_Base):
    """Confiance et source, pour les éléments d'une liste."""

    confiance: float | None = Field(
        None, ge=0, le=1, description="Confiance dans la lecture, de 0 (aucune) à 1 (certaine)."
    )
    source: Source | None = Field(None, description="Endroit du plan où l'élément a été lu.")


class Champ(_Base, Generic[T]):
    """Une valeur lue sur le plan, avec sa confiance et sa source."""

    valeur: T | None = Field(None, description="Valeur lue sur le plan, ou null si absente.")
    confiance: float | None = Field(
        None, ge=0, le=1, description="Confiance dans la lecture, de 0 (aucune) à 1 (certaine)."
    )
    source: Source | None = Field(None, description="Endroit du plan où la valeur a été lue.")


# --- Sections ---------------------------------------------------------------------------


class Identification(_Base):
    reference: Champ[str] = Field(
        default_factory=Champ[str], description="Référence ou numéro de pièce (cartouche)."
    )
    designation: Champ[str] = Field(
        default_factory=Champ[str],
        description="Désignation de la pièce (cartouche ou nomenclature), ex. « SUPPORT ».",
    )
    indice: Champ[str] = Field(
        default_factory=Champ[str], description="Indice de révision du plan, ex. « C »."
    )


class Matiere(_Base):
    designation: Champ[str] = Field(
        default_factory=Champ[str],
        description="Matière telle qu'écrite sur le plan, ex. « S235JR », « 6061-T6 Aluminum ».",
    )
    famille: Champ[FamilleMatiere] = Field(
        default_factory=Champ[FamilleMatiere],
        description="Famille de la matière, déduite de la désignation. Null si matière absente.",
    )
    epaisseur: Champ[float] = Field(
        default_factory=Champ[float], description="Épaisseur de la tôle, dans l'unité du plan."
    )


class Encombrement(_Base):
    """Dimensions hors-tout de la pièce finie (pliée), dans l'unité du plan."""

    longueur: Champ[float] = Field(
        default_factory=Champ[float], description="Plus grande dimension."
    )
    largeur: Champ[float] = Field(default_factory=Champ[float], description="Deuxième dimension.")
    hauteur: Champ[float] = Field(
        default_factory=Champ[float],
        description="Troisième dimension (hauteur de la pièce pliée, ou épaisseur si pièce plate).",
    )


class Aile(_Base):
    type: Literal["aile"] = "aile"
    longueur: float = Field(gt=0, description="Longueur de l'aile, dans l'unité du plan.")


class Pli(_Base):
    type: Literal["pli"] = "pli"
    angle: float = Field(
        gt=0,
        le=180,
        description=(
            "Angle de pliage en degrés = déviation par rapport à la tôle à plat. "
            "90 pour une équerre (et non l'angle intérieur restant entre les ailes)."
        ),
    )
    sens: Literal["haut", "bas", "inconnu"] = Field(
        "inconnu", description="Sens du pli en parcourant le profil de gauche à droite."
    )
    rayon_interieur: float | None = Field(
        None, description="Rayon intérieur de ce pli s'il est coté, sinon null."
    )


ElementProfil = Annotated[Aile | Pli, Field(discriminator="type")]


class ProfilPliage(_Trace):
    """Profil de la pièce vu de côté, pour des plis parallèles.

    Séquence alternée aile → pli → aile → … qui commence et finit par une aile.
    Exemple d'un Z : aile 18 → pli 90° haut → aile 22 → pli 90° bas → aile 42.
    Une pièce plate a une seule aile.
    """

    cotation: Literal["exterieure", "interieure", "inconnue"] = Field(
        "inconnue",
        description="Les longueurs d'ailes sont-elles cotées à l'extérieur ou à l'intérieur ?",
    )
    elements: list[ElementProfil] = Field(
        description="Ailes et plis, en alternance, de gauche à droite sur la vue de côté."
    )
    rayon_pliage_general: float | None = Field(
        None,
        description="Rayon de pliage donné par une note générale (ex. « BENDING RADIUS 2mm »).",
    )

    @property
    def nb_plis(self) -> int:
        return sum(isinstance(e, Pli) for e in self.elements)


class Trou(_Trace):
    """Un trou ou une découpe intérieure, ou un groupe de trous identiques (« 2x »)."""

    forme: Literal["rond", "oblong", "carre", "rectangulaire", "autre"] = "rond"
    diametre: float | None = Field(None, description="Diamètre, pour un trou rond.")
    longueur: float | None = Field(None, description="Longueur, pour un oblong ou un rectangle.")
    largeur: float | None = Field(None, description="Largeur, pour un oblong ou un rectangle.")
    quantite: int = Field(1, ge=1, description="Nombre de trous identiques (« 2x » → 2).")
    tolerance: str | None = Field(
        None, description="Tolérance sur la dimension, ex. « +0,1/0 », « H7 »."
    )
    tolerance_geometrique: str | None = Field(
        None, description="Tolérance géométrique associée, ex. « position 0,1 A B »."
    )
    filetage: str | None = Field(None, description="Taraudage éventuel, ex. « M6 ».")
    fraisurage: str | None = Field(
        None, description="Fraisure ou lamage éventuel, tel qu'écrit, ex. « fraisure 90° Ø12 »."
    )


class CoinCoupe(_Trace):
    """Chanfrein ou rayon sur un coin du contour extérieur."""

    type: Literal["chanfrein", "rayon"]
    cote1: float | None = Field(
        None, description="Première cote d'un chanfrein (20 pour « 20x20 »)."
    )
    cote2: float | None = Field(None, description="Seconde cote d'un chanfrein.")
    rayon: float | None = Field(None, description="Rayon d'un coin arrondi.")
    quantite: int = Field(1, ge=1, description="Nombre de coins identiques.")


class Contours(_Base):
    trous: list[Trou] = Field(default_factory=list, description="Trous et découpes intérieures.")
    coins: list[CoinCoupe] = Field(
        default_factory=list, description="Chanfreins et rayons de coin."
    )
    autres_decoupes: list[str] = Field(
        default_factory=list,
        description="Découpes ou formes particulières non décrites ailleurs, en texte libre.",
    )


class Soudure(_Trace):
    """Un cordon ou un groupe de points de soudure (« 4x »)."""

    procede: Literal["mig_mag", "tig", "points", "autre", "inconnu"] = Field(
        "inconnu", description="Procédé de soudage, s'il est indiqué."
    )
    type_joint: Literal["angle", "bout_a_bout", "bouchon", "autre", "inconnu"] = Field(
        "inconnu", description="Type de joint d'après le symbole de soudure."
    )
    longueur: float | None = Field(None, description="Longueur d'un cordon, si cotée.")
    gorge: float | None = Field(None, description="Épaisseur de gorge (« a3 » → 3).")
    quantite: int = Field(1, ge=1, description="Nombre de cordons ou de points identiques.")
    texte: str | None = Field(None, description="Annotation brute du symbole de soudure.")


class Composant(_Trace):
    """Composant acheté ajouté à la pièce (nomenclature)."""

    designation: str = Field(description="Désignation telle qu'écrite dans la nomenclature.")
    type: Literal[
        "ecrou_a_sertir", "goujon_a_sertir", "entretoise_a_sertir", "insert", "rivet", "autre"
    ]
    filetage: str | None = Field(None, description="Filetage, ex. « M6 ».")
    quantite: int = Field(1, ge=1)
    norme: str | None = Field(None, description="Norme ou spécification de pose citée sur le plan.")


class Traitement(_Base):
    designation: Champ[str] = Field(
        default_factory=Champ[str],
        description="Traitement de surface tel qu'écrit sur le plan, ex. « Anodized Type II ».",
    )
    type: Champ[TypeTraitement] = Field(
        default_factory=Champ[TypeTraitement],
        description="Type de traitement. « aucun » seulement si le plan l'indique ; null si non précisé.",
    )
    zones_epargne: list[str] = Field(
        default_factory=list,
        description="Zones à épargner du traitement, ex. « filetages ».",
    )


class Note(_Trace):
    texte: str = Field(
        description="Texte de la note. Pour une note bilingue, recopier une seule langue (la première)."
    )
    categorie: Literal[
        "pliage",
        "traitement",
        "assemblage",
        "soudure",
        "operation",
        "tolerance",
        "matiere",
        "general",
    ] = Field(
        description=(
            "Catégorie de la note. « operation » pour une opération de fabrication "
            "(ébavurage, marquage, contrôle…)."
        )
    )


class Cote(_Trace):
    """Une cote lue sur le plan, telle qu'écrite, sans interprétation."""

    valeur: float = Field(description="Valeur principale de la cote.")
    type: Literal["lineaire", "diametre", "rayon", "angle", "chanfrein"] = "lineaire"
    quantite: int = Field(1, ge=1, description="Multiplicateur écrit devant la cote (« 2x » → 2).")
    tolerance: str | None = Field(None, description="Tolérance écrite avec la cote.")
    theorique: bool = Field(False, description="Cote encadrée (cote théorique exacte).")
    texte: str | None = Field(None, description="Texte brut de la cote, ex. « 2X Ø8,75 +0,1/0 ».")


class ToleranceGeometrique(_Trace):
    """Un cadre de tolérance géométrique, ex. « ⌖ 0,1 A B »."""

    type: Literal[
        "planeite",
        "rectitude",
        "circularite",
        "cylindricite",
        "profil_ligne",
        "profil_surface",
        "parallelisme",
        "perpendicularite",
        "inclinaison",
        "position",
        "concentricite",
        "symetrie",
        "battement",
        "battement_total",
        "autre",
    ] = Field(description="Caractéristique tolérancée, d'après le symbole du cadre.")
    valeur: float = Field(description="Valeur de la tolérance (zone de tolérance).")
    references: str | None = Field(
        None, description="Références (datums) citées dans le cadre, ex. « A B »."
    )
    quantite: int = Field(1, ge=1, description="Nombre de cadres identiques.")
    texte: str | None = Field(None, description="Contenu brut du cadre.")


class EtatSurface(_Trace):
    """Une indication de rugosité, ex. « Ra 1,6 µm » ou « 63 RMS »."""

    valeur: float | None = Field(None, description="Valeur numérique de la rugosité.")
    texte: str = Field(description="Indication telle qu'écrite, ex. « Ra 1.6 µm ».")


class Anomalie(_Base):
    """Problème signalé par l'IA plutôt que de deviner une valeur."""

    type: Literal["information_manquante", "incoherence", "illisible", "autre"]
    champ: str | None = Field(None, description="Champ concerné, ex. « matiere.designation ».")
    description: str


# --- Pièce ------------------------------------------------------------------------------


class PieceExtraite(_Base):
    """Toutes les informations utiles au devis, lues sur un plan de tôlerie."""

    version_schema: Literal["1.2"] = VERSION_SCHEMA
    unites: Champ[Unite] = Field(
        default_factory=Champ[Unite], description="Unité des cotes du plan (mm ou in)."
    )
    identification: Identification = Field(default_factory=Identification)
    matiere: Matiere = Field(default_factory=Matiere)
    encombrement: Encombrement = Field(default_factory=Encombrement)
    profil_pliage: ProfilPliage | None = Field(
        None, description="Profil de pliage. Null si la vue de côté ne permet pas de le déterminer."
    )
    contours: Contours = Field(default_factory=Contours)
    composants: list[Composant] = Field(
        default_factory=list, description="Composants de la nomenclature, hors pièce elle-même."
    )
    soudures: list[Soudure] = Field(
        default_factory=list, description="Soudures indiquées sur le plan (symboles ou notes)."
    )
    traitement: Traitement = Field(default_factory=Traitement)
    tolerance_generale: Champ[str] = Field(
        default_factory=Champ[str], description="Tolérance générale, ex. « ISO 2768-m »."
    )
    tolerances_geometriques: list[ToleranceGeometrique] = Field(
        default_factory=list,
        description="Tous les cadres de tolérance géométrique du plan, y compris ceux des trous.",
    )
    etats_surface: list[EtatSurface] = Field(
        default_factory=list, description="Indications de rugosité (états de surface)."
    )
    notes: list[Note] = Field(
        default_factory=list,
        description=(
            "Notes écrites du plan (bloc de notes, remarques). Sans le cartouche, l'échelle, "
            "le traitement, les états de surface ni les tolérances géométriques."
        ),
    )
    cotes: list[Cote] = Field(
        default_factory=list, description="Toutes les cotes lues sur le plan."
    )
    anomalies: list[Anomalie] = Field(
        default_factory=list,
        description="Informations manquantes, incohérentes ou illisibles. Signaler plutôt que deviner.",
    )

    def problemes_coherence(self) -> list[str]:
        """Contrôles de structure simples, faits par le code après l'extraction.

        On ne rejette pas la réponse : on liste les problèmes, pour les compter et les afficher.
        """
        problemes: list[str] = []
        if self.profil_pliage is not None:
            elements = self.profil_pliage.elements
            if not elements:
                problemes.append("profil_pliage : aucun élément")
            for i, element in enumerate(elements):
                attendu = Aile if i % 2 == 0 else Pli
                if not isinstance(element, attendu):
                    problemes.append(
                        f"profil_pliage : élément {i} devrait être un(e) {attendu.__name__.lower()}"
                    )
            if elements and not isinstance(elements[-1], Aile):
                problemes.append("profil_pliage : le profil doit finir par une aile")
        for i, trou in enumerate(self.contours.trous):
            if trou.forme == "rond" and trou.diametre is None:
                problemes.append(f"contours.trous[{i}] : trou rond sans diamètre")
        return problemes
