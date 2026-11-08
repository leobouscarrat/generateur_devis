"""Comparaison champ par champ entre une extraction et la bonne réponse.

Deux sortes de champs :
- champs « simples » (une valeur) : statut juste / faux / manquant / inventé / déduit signalé ;
- champs « listes » (cotes, notes, trous…) : appariement des éléments, puis rappel et précision.

Règles (voir docs/evaluation.md §6.1) :
- textes comparés après normalisation (casse, accents, espaces, ponctuation) ;
- nombres comparés à la valeur imprimée (écart relatif ≤ 0,1 %) ;
- profil de pliage accepté dans les deux sens de lecture ;
- une valeur donnée alors que le plan n'en contient pas est une invention, sauf si l'IA l'a
  signalée (anomalie sur ce champ ou confiance < 0,5) : c'est alors une déduction signalée.
"""

import math
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from generateur_devis.schema import PieceExtraite

SEUIL_CONFIANCE_SIGNALEE = 0.5
SEUIL_SIMILARITE_TEXTE = 0.8


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", texte.upper())


def egal_nombre(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=1e-6)


# --- Champs simples ------------------------------------------------------------------------


@dataclass
class ResultatChamp:
    champ: str
    statut: str
    """juste | faux | manquant | invente | deduit_signale | absent_ok (pour un champ simple),
    liste (pour un champ liste : voir apparies / attendus / lus)."""
    attendu: Any = None
    lu: Any = None
    apparies: int = 0
    attendus: int = 0
    lus: int = 0


def _valeur(piece: PieceExtraite, chemin: str):
    objet = piece
    for cle in chemin.split("."):
        objet = getattr(objet, cle)
    return objet.valeur, objet.confiance


def _encombrement(piece: PieceExtraite):
    e = piece.encombrement
    valeurs = [e.longueur.valeur, e.largeur.valeur, e.hauteur.valeur]
    if all(v is None for v in valeurs):
        return None, None
    confiances = [
        c for c in (e.longueur.confiance, e.largeur.confiance, e.hauteur.confiance) if c is not None
    ]
    # L'ordre longueur / largeur / hauteur est ambigu : on compare les trois valeurs triées.
    return tuple(sorted(v for v in valeurs if v is not None)), min(confiances, default=None)


def _profil(piece: PieceExtraite):
    profil = piece.profil_pliage
    if profil is None:
        return None, None
    elements = tuple(
        ("aile", round(e.longueur, 3)) if e.type == "aile" else ("pli", round(e.angle, 1))
        for e in profil.elements
    )
    return elements, profil.confiance


def _nb_plis(piece: PieceExtraite):
    profil = piece.profil_pliage
    return (profil.nb_plis, profil.confiance) if profil else (None, None)


def _nb_soudures(piece: PieceExtraite):
    return sum(s.quantite for s in piece.soudures), None


def _egal(attendu, lu) -> bool:
    if isinstance(attendu, int | float) and isinstance(lu, int | float):
        return egal_nombre(attendu, lu)
    if isinstance(attendu, str) and isinstance(lu, str):
        return normaliser(attendu) == normaliser(lu)
    if isinstance(attendu, tuple) and isinstance(lu, tuple):
        if attendu and isinstance(attendu[0], tuple):  # profil : accepté dans les deux sens
            return _profils_egaux(attendu, lu) or _profils_egaux(attendu, tuple(reversed(lu)))
        return len(attendu) == len(lu) and all(
            _egal(a, b) for a, b in zip(attendu, lu, strict=True)
        )
    return attendu == lu


def _profils_egaux(a: tuple, b: tuple) -> bool:
    return len(a) == len(b) and all(
        x[0] == y[0] and egal_nombre(x[1], y[1]) for x, y in zip(a, b, strict=True)
    )


def _signale(piece: PieceExtraite, champ: str, confiance: float | None) -> bool:
    if confiance is not None and confiance < SEUIL_CONFIANCE_SIGNALEE:
        return True
    racine = champ.split(".")[0]
    return any(
        a.champ and (a.champ.startswith(champ) or a.champ.startswith(racine))
        for a in piece.anomalies
    )


def comparer_simple(
    champ: str, lecteur: Callable, verite: PieceExtraite, extraction: PieceExtraite
) -> ResultatChamp:
    attendu, _ = lecteur(verite)
    lu, confiance = lecteur(extraction)
    if attendu is None and lu is None:
        statut = "absent_ok"
    elif attendu is None:
        statut = "deduit_signale" if _signale(extraction, champ, confiance) else "invente"
    elif lu is None:
        statut = "manquant"
    else:
        statut = "juste" if _egal(attendu, lu) else "faux"
    return ResultatChamp(champ, statut, attendu, lu)


# --- Champs listes --------------------------------------------------------------------------


def _apparier(attendus: list, lus: list, egal: Callable[[Any, Any], bool]) -> int:
    """Appariement glouton : chaque élément lu ne peut servir qu'une fois."""
    restants = list(lus)
    apparies = 0
    for a in attendus:
        for i, b in enumerate(restants):
            if egal(a, b):
                apparies += 1
                del restants[i]
                break
    return apparies


def _premier_nombre(texte: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", texte)
    return float(m.group().replace(",", ".")) if m else None


def _texte_proche(a: str, b: str) -> bool:
    a, b = normaliser(a), normaliser(b)
    return a == b or SequenceMatcher(None, a, b).ratio() >= SEUIL_SIMILARITE_TEXTE


def _egal_lie(a, b) -> bool:
    if isinstance(a, tuple):
        return len(a) == len(b) and all(_egal(x, y) for x, y in zip(a, b, strict=True))
    return _egal(a, b)


LISTES: dict[str, tuple[Callable[[PieceExtraite], list], Callable[[Any, Any], bool]]] = {
    "cotes": (lambda p: [c.valeur for c in p.cotes], egal_nombre),
    "notes": (lambda p: [n.texte for n in p.notes], _texte_proche),
    "trous": (
        lambda p: [t.diametre or 0.0 for t in p.contours.trous for _ in range(t.quantite)],
        egal_nombre,
    ),
    "coins": (
        lambda p: [
            (c.type, c.cote1 if c.type == "chanfrein" else c.rayon)
            for c in p.contours.coins
            for _ in range(c.quantite)
        ],
        _egal_lie,
    ),
    "composants": (
        lambda p: [(c.type, c.filetage or "") for c in p.composants for _ in range(c.quantite)],
        _egal_lie,
    ),
    "traitement.zones_epargne": (lambda p: list(p.traitement.zones_epargne), _texte_proche),
    # Valeur seule (ce qui compte pour le prix), puis type + valeur (lecture du symbole).
    "tolerances_geometriques": (
        lambda p: [t.valeur for t in p.tolerances_geometriques for _ in range(t.quantite)],
        egal_nombre,
    ),
    "tolerances_geometriques.type": (
        lambda p: [
            (t.type, t.valeur) for t in p.tolerances_geometriques for _ in range(t.quantite)
        ],
        _egal_lie,
    ),
    "etats_surface": (
        lambda p: [
            e.valeur if e.valeur is not None else _premier_nombre(e.texte) for e in p.etats_surface
        ],
        lambda a, b: a is not None and b is not None and egal_nombre(a, b),
    ),
}


def comparer_liste(champ: str, verite: PieceExtraite, extraction: PieceExtraite) -> ResultatChamp:
    lecteur, egal = LISTES[champ]
    attendus, lus = lecteur(verite), lecteur(extraction)
    apparies = _apparier(attendus, lus, egal)
    return ResultatChamp(champ, "liste", attendus, lus, apparies, len(attendus), len(lus))


# --- Registre ------------------------------------------------------------------------------

SIMPLES: dict[str, Callable] = {
    "unites": lambda p: _valeur(p, "unites"),
    "identification.reference": lambda p: _valeur(p, "identification.reference"),
    "identification.designation": lambda p: _valeur(p, "identification.designation"),
    "identification.indice": lambda p: _valeur(p, "identification.indice"),
    "matiere.designation": lambda p: _valeur(p, "matiere.designation"),
    "matiere.famille": lambda p: _valeur(p, "matiere.famille"),
    "matiere.epaisseur": lambda p: _valeur(p, "matiere.epaisseur"),
    "encombrement": _encombrement,
    "profil_pliage": _profil,
    "nb_plis": _nb_plis,
    "traitement.designation": lambda p: _valeur(p, "traitement.designation"),
    "traitement.type": lambda p: _valeur(p, "traitement.type"),
    "tolerance_generale": lambda p: _valeur(p, "tolerance_generale"),
    "soudures": _nb_soudures,
}

CHAMPS = list(SIMPLES) + list(LISTES)


def comparer(
    verite: PieceExtraite, extraction: PieceExtraite, champs: list[str] | None = None
) -> list[ResultatChamp]:
    resultats = []
    for champ in champs or CHAMPS:
        if champ in SIMPLES:
            resultats.append(comparer_simple(champ, SIMPLES[champ], verite, extraction))
        elif champ in LISTES:
            resultats.append(comparer_liste(champ, verite, extraction))
        else:
            raise ValueError(f"Champ inconnu : {champ}")
    return resultats
