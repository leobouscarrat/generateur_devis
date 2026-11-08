"""Jeux d'évaluation : plans + bonnes réponses au format de la pièce.

Chaque jeu fournit des `Echantillon` et la liste des champs qu'il permet d'évaluer : un jeu
public ne couvre qu'une partie du format (cadsy : les cotes ; ecado : le texte du plan).

Découpage développement / test : tirage aléatoire à graine fixe, donc reproductible.
Les données téléchargées sont rangées dans data/raw/ (hors du dépôt).
"""

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from generateur_devis.extraction.documents import Plan, charger_plan
from generateur_devis.llm.base import Image
from generateur_devis.schema import (
    Champ,
    Contours,
    Cote,
    Identification,
    Matiere,
    Note,
    PieceExtraite,
    Soudure,
    Traitement,
)

RACINE = Path(__file__).resolve().parents[3]
DOSSIER_RAW = RACINE / "data" / "raw"
GRAINE = 2026


@dataclass
class Echantillon:
    jeu: str
    identifiant: str
    plan: Plan
    verite: PieceExtraite


@dataclass
class Jeu:
    nom: str
    champs: list[str]
    """Champs évalués sur ce jeu (voir comparaison.CHAMPS)."""
    echantillons: list[Echantillon]


def _decouper(identifiants: list[str], partie: str, n_dev: int, n_test: int) -> list[str]:
    melange = sorted(identifiants)
    random.Random(GRAINE).shuffle(melange)
    if partie == "dev":
        return melange[:n_dev]
    if partie == "test":
        return melange[n_dev : n_dev + n_test]
    raise ValueError("partie : « dev » ou « test »")


def _type_mime(donnees: bytes) -> str:
    if donnees.startswith(b"\x89PNG"):
        return "image/png"
    if donnees.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "image/webp"


def _nombre(texte: str) -> float:
    return float(texte.replace(",", "."))


# --- cadsy : plans réalistes, lecture des cotes -------------------------------------------

URL_CADSY = "https://huggingface.co/datasets/cadsy/cad-technical-drawings/resolve/main"
CHAMPS_CADSY = ["tolerance_generale", "cotes"]
_ANNOTATION_CADSY = re.compile(r"^(?:(\d+)\s*×\s*)?([⌀RC])\s*(\d+(?:[.,]\d+)?)")


def _telecharger(url: str, chemin: Path) -> Path:
    if not chemin.exists():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        reponse = httpx.get(url, follow_redirects=True, timeout=120)
        reponse.raise_for_status()
        chemin.write_bytes(reponse.content)
    return chemin


def _cotes_cadsy(annotations: list[dict]) -> list[Cote]:
    """Cotes simples (« 22,5 ») et annotations ⌀ / R / C (« 2×R5 », « ⌀3 ±0,05 ↧10 »).

    Les annotations composées (oblongs « 4×7 × 29 ↧2,5 ») sont ignorées : on mesure donc
    surtout le rappel (part des cotes retrouvées), la précision n'est qu'indicative.
    """
    cotes = []
    for a in annotations:
        texte = a["text"].strip()
        if a["type"] == "dimension" and re.fullmatch(r"\d+(?:[.,]\d+)?", texte):
            cotes.append(Cote(valeur=_nombre(texte), texte=texte))
        elif a["type"] == "callout" and (m := _ANNOTATION_CADSY.match(texte)):
            quantite, symbole, valeur = m.groups()
            type_cote = {"⌀": "diametre", "R": "rayon", "C": "chanfrein"}[symbole]
            cotes.append(
                Cote(
                    valeur=_nombre(valeur), type=type_cote, quantite=int(quantite or 1), texte=texte
                )
            )
    return cotes


def charger_cadsy(partie: str, n_dev: int = 5, n_test: int = 30) -> Jeu:
    dossier = DOSSIER_RAW / "cadsy"
    meta = _telecharger(f"{URL_CADSY}/metadata.jsonl", dossier / "metadata.jsonl")
    lignes = [json.loads(ligne) for ligne in meta.read_text().splitlines() if ligne.strip()]
    choisis = set(_decouper([ligne["part_id"] for ligne in lignes], partie, n_dev, n_test))

    echantillons = []
    for ligne in lignes:
        if ligne["part_id"] not in choisis:
            continue
        image = _telecharger(f"{URL_CADSY}/{ligne['iso_image']}", dossier / ligne["iso_image"])
        labels = _telecharger(f"{URL_CADSY}/{ligne['iso_labels']}", dossier / ligne["iso_labels"])
        annotations = json.loads(labels.read_text())["annotations"]
        tolerance = next(
            (a["text"] for a in annotations if re.match(r"ISO\s*2768", a["text"])), None
        )
        verite = PieceExtraite(
            unites=Champ(valeur="mm"),
            tolerance_generale=Champ(valeur=tolerance),
            cotes=_cotes_cadsy(annotations),
        )
        echantillons.append(Echantillon("cadsy", ligne["part_id"], charger_plan(image), verite))
    return Jeu("cadsy", CHAMPS_CADSY, sorted(echantillons, key=lambda e: e.identifiant))


# --- ecado : plans orientés devis, texte du plan ------------------------------------------

URL_ECADO = "https://huggingface.co/datasets/ecado/rfq-engineering-drawings/resolve/main/data"
CHAMPS_ECADO = [
    "unites",
    "identification.reference",
    "identification.designation",
    "identification.indice",
    "matiere.designation",
    "matiere.famille",
    "traitement.designation",
    "traitement.type",
    "tolerance_generale",
    "soudures",
    "notes",
    "cotes",
]

_FAMILLES = [
    ("stainless", "inox"),
    ("inconel", "autre"),
    ("alumin", "aluminium"),
    ("brass", "laiton"),
    ("copper", "cuivre"),
    ("titanium", "titane"),
    ("steel", "acier"),
]
_TRAITEMENTS = [
    ("zinc", "zingage"),
    ("passiv", "passivation"),
    ("anodi", "anodisation"),
    ("powder", "thermolaquage"),
    ("galvaniz", "galvanisation"),
    ("paint", "peinture"),
    ("none", "aucun"),
]
_SOUDURES = {"fillet": "angle", "butt": "bout_a_bout", "groove": "bout_a_bout", "plug": "bouchon"}


def _correspondance(texte: str, table: list[tuple[str, str]], defaut: str) -> str:
    texte = texte.lower()
    return next((valeur for motif, valeur in table if motif in texte), defaut)


def _verite_ecado(gt: dict) -> PieceExtraite:
    cartouche = gt["title_block"]
    tolerance = next(
        (
            n.split(":", 1)[1].strip()
            for n in gt["notes"]
            if n.upper().startswith("GENERAL TOLERANCE")
        ),
        None,
    )
    traitement = gt["treatment"]
    return PieceExtraite(
        unites=Champ(valeur=cartouche["units"]),
        identification=Identification(
            reference=Champ(valeur=cartouche["part_number"]),
            designation=Champ(valeur=cartouche["title"]),
            indice=Champ(valeur=cartouche["revision"]),
        ),
        matiere=Matiere(
            designation=Champ(valeur=cartouche["material"]),
            famille=Champ(valeur=_correspondance(cartouche["material"], _FAMILLES, "autre")),
        ),
        traitement=Traitement(
            designation=Champ(valeur=traitement),
            type=Champ(valeur=_correspondance(traitement, _TRAITEMENTS, "autre")),
        ),
        tolerance_generale=Champ(valeur=tolerance),
        soudures=[
            Soudure(
                procede="points" if s["type"] == "spot" else "inconnu",
                type_joint=_SOUDURES.get(s["type"], "autre"),
            )
            for s in gt["weld_symbols"]
        ],
        notes=[Note(texte=n, categorie="general") for n in gt["notes"]],
        cotes=[
            Cote(valeur=d["value"], tolerance=d.get("tolerance"), texte=f"{d['value']} {d['unit']}")
            for d in gt["dimensions"]
        ],
        contours=Contours(),
    )


def charger_ecado(partie: str, n_dev: int = 5, n_test: int = 40) -> Jeu:
    # Développement sur « validation », test sur « test » : les deux ne se recouvrent jamais.
    split = "validation" if partie == "dev" else "test"
    chemin = _telecharger(
        f"{URL_ECADO}/{split}-00000-of-00001.parquet", DOSSIER_RAW / "ecado" / f"{split}.parquet"
    )
    lignes = pq.read_table(chemin).to_pylist()
    identifiants = [f"{split}-{i:03d}" for i in range(len(lignes))]
    n = n_dev if partie == "dev" else n_test
    choisis = set(_decouper(identifiants, "dev", n, 0))  # premier tirage de n dans ce split

    echantillons = []
    for identifiant, ligne in zip(identifiants, lignes, strict=True):
        if identifiant not in choisis:
            continue
        donnees = ligne["image"]["bytes"]
        plan = Plan(Path(f"ecado/{identifiant}"), [Image(donnees, _type_mime(donnees))], "")
        verite = _verite_ecado(json.loads(ligne["ground_truth"])["gt_parse"])
        echantillons.append(Echantillon("ecado", identifiant, plan, verite))
    return Jeu("ecado", CHAMPS_ECADO, echantillons)


# --- plans privés annotés à la main (ex. piece_003) ---------------------------------------

DOSSIER_PRIVE = RACINE / "data" / "prive"


def charger_prive() -> Jeu:
    """Plans de data/prive/plans/ ou exercise_information/, annotés dans data/prive/annotations/."""
    from generateur_devis.evaluation.comparaison import CHAMPS

    echantillons = []
    for annotation in sorted((DOSSIER_PRIVE / "annotations").glob("*.json")):
        candidats = [
            dossier / f"{annotation.stem}{ext}"
            for dossier in (DOSSIER_PRIVE / "plans", RACINE / "exercise_information")
            for ext in (".pdf", ".png", ".jpg")
        ]
        plan = next((c for c in candidats if c.exists()), None)
        if plan is None:
            continue
        verite = PieceExtraite.model_validate_json(annotation.read_text(encoding="utf-8"))
        echantillons.append(Echantillon("prive", annotation.stem, charger_plan(plan), verite))
    return Jeu("prive", list(CHAMPS), echantillons)


def charger_jeu(nom: str, partie: str = "dev") -> Jeu:
    if nom == "cadsy":
        return charger_cadsy(partie)
    if nom == "ecado":
        return charger_ecado(partie)
    if nom == "prive":
        return charger_prive()
    raise ValueError(f"Jeu inconnu : {nom} (cadsy, ecado, prive)")
