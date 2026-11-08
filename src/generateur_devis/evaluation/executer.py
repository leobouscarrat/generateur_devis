"""Exécution d'une évaluation : un jeu × un modèle → résultats détaillés + synthèse par champ."""

import json
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from generateur_devis.evaluation.comparaison import ResultatChamp, comparer
from generateur_devis.evaluation.jeux import Echantillon, Jeu
from generateur_devis.extraction import VERSION_PROMPT, extraire
from generateur_devis.extraction.extracteur import ResultatExtraction
from generateur_devis.llm.base import ModeleVision

DOSSIER_RUNS = Path(__file__).resolve().parents[3] / "results" / "runs"
STATUTS_ACCEPTABLES = {"juste", "absent_ok", "deduit_signale"}


@dataclass
class ResultatEchantillon:
    identifiant: str
    extraction: ResultatExtraction
    champs: list[ResultatChamp] = field(default_factory=list)


def evaluer_echantillon(
    echantillon: Echantillon, modele: ModeleVision, champs: list[str]
) -> ResultatEchantillon:
    extraction = extraire(echantillon.plan, modele)
    resultat = ResultatEchantillon(echantillon.identifiant, extraction)
    if extraction.piece is not None:
        resultat.champs = comparer(echantillon.verite, extraction.piece, champs)
    return resultat


def intervalle_wilson(succes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance à 95 % d'une proportion (méthode de Wilson)."""
    if n == 0:
        return (0.0, 0.0)
    p = succes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    marge = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - marge), min(1.0, centre + marge))


def synthese(jeu: Jeu, resultats: list[ResultatEchantillon]) -> dict:
    valides = [r for r in resultats if r.extraction.piece is not None]
    couts = [r.extraction.cout_usd for r in resultats if r.extraction.cout_usd is not None]
    champs = {}
    for nom in jeu.champs:
        lignes = [c for r in valides for c in r.champs if c.champ == nom]
        if not lignes:
            continue
        if lignes[0].statut == "liste":
            apparies = sum(c.apparies for c in lignes)
            attendus = sum(c.attendus for c in lignes)
            lus = sum(c.lus for c in lignes)
            champs[nom] = {
                "type": "liste",
                "rappel": apparies / attendus if attendus else None,
                "rappel_ic95": intervalle_wilson(apparies, attendus),
                "precision": apparies / lus if lus else None,
                "attendus": attendus,
                "lus": lus,
            }
        else:
            statuts = Counter(c.statut for c in lignes)
            acceptables = sum(statuts[s] for s in STATUTS_ACCEPTABLES)
            champs[nom] = {
                "type": "simple",
                "n": len(lignes),
                "exactitude": acceptables / len(lignes),
                "exactitude_ic95": intervalle_wilson(acceptables, len(lignes)),
                "statuts": dict(statuts),
            }
    return {
        "jeu": jeu.nom,
        "plans": len(resultats),
        "reponses_valides": len(valides),
        "cout_usd": sum(couts) if couts else None,
        "duree_s": sum(r.extraction.duree_s for r in resultats),
        "champs": champs,
    }


def executer(
    jeu: Jeu, modele: ModeleVision, partie: str, paralleles: int = 2
) -> tuple[list[ResultatEchantillon], dict, Path]:
    with ThreadPoolExecutor(max_workers=paralleles) as executeur:
        resultats = list(
            executeur.map(lambda e: evaluer_echantillon(e, modele, jeu.champs), jeu.echantillons)
        )
    resume = synthese(jeu, resultats)
    resume.update(modele=modele.nom, version_prompt=VERSION_PROMPT, partie=partie)

    DOSSIER_RUNS.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    nom = f"{horodatage}_{jeu.nom}_{partie}_{modele.nom.replace('/', '_').replace(':', '_')}_{VERSION_PROMPT}"
    chemin = DOSSIER_RUNS / f"{nom}.json"
    detail = [
        {
            "identifiant": r.identifiant,
            "erreur": r.extraction.erreur,
            "problemes": r.extraction.problemes,
            "cout_usd": r.extraction.cout_usd,
            "duree_s": r.extraction.duree_s,
            "depuis_cache": r.extraction.depuis_cache,
            "champs": [asdict(c) for c in r.champs],
        }
        for r in resultats
    ]
    chemin.write_text(
        json.dumps(
            {"synthese": resume, "detail": detail}, ensure_ascii=False, indent=2, default=str
        ),
        encoding="utf-8",
    )
    return resultats, resume, chemin


def tableau(resume: dict) -> str:
    """Synthèse lisible en Markdown."""
    cout = f"{resume['cout_usd']:.2f} $" if resume["cout_usd"] is not None else "inconnu"
    lignes = [
        f"**{resume['jeu']} / {resume['partie']}** — modèle `{resume['modele']}`, prompt {resume['version_prompt']}",
        f"{resume['reponses_valides']}/{resume['plans']} réponses valides · coût {cout} · "
        f"{resume['duree_s']:.0f} s cumulées",
        "",
        "| Champ | Score | IC 95 % | Détail |",
        "|---|---|---|---|",
    ]
    for nom, c in resume["champs"].items():
        if c["type"] == "liste":
            bas, haut = c["rappel_ic95"]
            precision = f"{c['precision']:.0%}" if c["precision"] is not None else "–"
            score = f"rappel {c['rappel']:.0%}" if c["rappel"] is not None else "–"
            detail = f"{c['attendus']} attendus, {c['lus']} lus, précision {precision}"
        else:
            bas, haut = c["exactitude_ic95"]
            score = f"{c['exactitude']:.0%}"
            detail = ", ".join(f"{s} {n}" for s, n in sorted(c["statuts"].items()))
        lignes.append(f"| {nom} | {score} | {bas:.0%} – {haut:.0%} | {detail} |")
    return "\n".join(lignes)
