"""Extraction d'une pièce à partir d'un plan, avec un modèle donné.

- La réponse du modèle est validée avec le format de la pièce. En cas d'échec, le modèle
  reçoit les erreurs et peut corriger sa réponse (une fois par défaut).
- Chaque réponse est mise en cache sur disque : un même plan, avec le même modèle et la même
  version du prompt, n'est jamais redemandé (on ne paie pas deux fois).
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import ValidationError

from generateur_devis.extraction.documents import Plan
from generateur_devis.extraction.prompt import (
    VERSION_PROMPT,
    prompt_correction,
    prompt_systeme,
    prompt_utilisateur,
)
from generateur_devis.llm.base import ErreurModele, ModeleVision, ReponseModele
from generateur_devis.schema import VERSION_SCHEMA, PieceExtraite

DOSSIER_CACHE = Path(__file__).resolve().parents[3] / "results" / "cache"


@dataclass
class ResultatExtraction:
    modele: str
    version_prompt: str
    piece: PieceExtraite | None
    erreur: str | None
    problemes: list[str] = field(default_factory=list)
    reponses: list[ReponseModele] = field(default_factory=list)
    depuis_cache: bool = False

    @property
    def cout_usd(self) -> float | None:
        couts = [r.cout_usd for r in self.reponses if r.cout_usd is not None]
        return sum(couts) if couts else None

    @property
    def duree_s(self) -> float:
        return sum(r.duree_s for r in self.reponses)


def extraire_json(texte: str) -> str:
    """Isole l'objet JSON d'une réponse, même entourée de texte ou de balises ```json."""
    texte = re.sub(r"```(?:json)?", "", texte)
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin <= debut:
        raise ValueError("aucun objet JSON dans la réponse")
    return texte[debut : fin + 1]


def _valider(texte: str) -> tuple[PieceExtraite | None, str | None]:
    try:
        return PieceExtraite.model_validate_json(extraire_json(texte)), None
    except (ValueError, ValidationError) as e:
        return None, str(e)[:3000]


def cle_cache(modele: str, plan: Plan, tentatives: int) -> str:
    empreinte = hashlib.sha256()
    for morceau in (modele, VERSION_PROMPT, VERSION_SCHEMA, str(tentatives), plan.texte):
        empreinte.update(morceau.encode())
    for image in plan.images:
        empreinte.update(image.donnees)
    return empreinte.hexdigest()[:24]


def _lire_cache(chemin: Path) -> ResultatExtraction | None:
    if not chemin.exists():
        return None
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    piece = PieceExtraite.model_validate(donnees["piece"]) if donnees["piece"] else None
    return ResultatExtraction(
        modele=donnees["modele"],
        version_prompt=donnees["version_prompt"],
        piece=piece,
        erreur=donnees["erreur"],
        problemes=donnees["problemes"],
        reponses=[ReponseModele(**r) for r in donnees["reponses"]],
        depuis_cache=True,
    )


def _ecrire_cache(chemin: Path, resultat: ResultatExtraction) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    donnees = {
        "modele": resultat.modele,
        "version_prompt": resultat.version_prompt,
        "piece": resultat.piece.model_dump(mode="json") if resultat.piece else None,
        "erreur": resultat.erreur,
        "problemes": resultat.problemes,
        "reponses": [asdict(r) for r in resultat.reponses],
    }
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def extraire(
    plan: Plan,
    modele: ModeleVision,
    tentatives: int = 2,
    dossier_cache: Path | None = DOSSIER_CACHE,
) -> ResultatExtraction:
    chemin_cache = None
    if dossier_cache is not None:
        chemin_cache = dossier_cache / f"{cle_cache(modele.nom, plan, tentatives)}.json"
        en_cache = _lire_cache(chemin_cache)
        if en_cache is not None:
            return en_cache

    resultat = ResultatExtraction(modele.nom, VERSION_PROMPT, None, None)
    systeme = prompt_systeme()
    message = prompt_utilisateur(plan.texte)
    for _ in range(tentatives):
        try:
            reponse = modele.generer(systeme, message, plan.images)
        except ErreurModele as e:
            # Erreur d'accès (quota, réseau…) : rien n'est mis en cache, on pourra réessayer.
            resultat.erreur = str(e)
            return resultat
        resultat.reponses.append(reponse)
        piece, erreur = _valider(reponse.texte)
        resultat.piece, resultat.erreur = piece, erreur
        if piece is not None:
            resultat.problemes = piece.problemes_coherence()
            break
        message = prompt_utilisateur(plan.texte) + "\n\n" + prompt_correction(reponse.texte, erreur)

    if chemin_cache is not None:
        _ecrire_cache(chemin_cache, resultat)
    return resultat
