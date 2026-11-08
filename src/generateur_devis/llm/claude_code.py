"""Accès à Claude via Claude Code en mode non interactif, avec la connexion de l'abonnement.

L'appel est réduit au minimum pour consommer peu de quota : notre propre prompt système,
aucun outil, aucun réglage ni serveur MCP chargé, aucune session enregistrée. L'image est
envoyée dans un message au format « stream-json ».
"""

import base64
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from generateur_devis.llm.base import ErreurModele, Image, ReponseModele

MOTIF_EXTENSION_VSCODE = (
    "~/.vscode*/extensions/anthropic.claude-code-*/resources/native-binary/claude"
)


def trouver_executable() -> str:
    """Cherche Claude Code : variable CLAUDE_BIN, puis commande `claude`, puis extension VS Code."""
    depuis_env = os.environ.get("CLAUDE_BIN", "").strip()
    if depuis_env:
        return depuis_env
    dans_path = shutil.which("claude")
    if dans_path:
        return dans_path
    candidats = glob.glob(os.path.expanduser(MOTIF_EXTENSION_VSCODE))
    candidats += glob.glob(
        os.path.expanduser(MOTIF_EXTENSION_VSCODE.replace(".vscode*", ".vscode-server"))
    )
    if candidats:
        # La version la plus récente de l'extension (dossier modifié en dernier).
        return max(set(candidats), key=lambda c: Path(c).stat().st_mtime)
    raise ErreurModele(
        "Claude Code introuvable : renseigner CLAUDE_BIN dans .env "
        "ou installer la commande (npm install -g @anthropic-ai/claude-code)."
    )


class ClaudeCode:
    def __init__(self, modele: str = "sonnet", executable: str | None = None, timeout_s: int = 300):
        self.modele = modele
        self.executable = executable or trouver_executable()
        self.timeout_s = timeout_s
        self.nom = f"claude-code:{modele}"

    def _commande(self, prompt_systeme: str) -> list[str]:
        return [
            self.executable,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--system-prompt", prompt_systeme,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--model", self.modele,
        ]  # fmt: skip

    def generer(
        self, prompt_systeme: str, prompt_utilisateur: str, images: list[Image]
    ) -> ReponseModele:
        contenu: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.type_mime,
                    "data": base64.b64encode(image.donnees).decode(),
                },
            }
            for image in images
        ]
        contenu.append({"type": "text", "text": prompt_utilisateur})
        message = {"type": "user", "message": {"role": "user", "content": contenu}}

        debut = time.monotonic()
        # Dossier temporaire : aucun fichier du projet (CLAUDE.md…) n'est chargé.
        with tempfile.TemporaryDirectory() as dossier:
            try:
                processus = subprocess.run(
                    self._commande(prompt_systeme),
                    input=json.dumps(message) + "\n",
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    cwd=dossier,
                )
            except subprocess.TimeoutExpired as e:
                raise ErreurModele(f"Claude Code : délai dépassé ({self.timeout_s} s)") from e
        duree = time.monotonic() - debut

        resultat = None
        for ligne in processus.stdout.splitlines():
            try:
                evenement = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if evenement.get("type") == "result":
                resultat = evenement
        if resultat is None:
            raise ErreurModele(
                f"Claude Code : pas de résultat (code {processus.returncode}) : "
                f"{processus.stderr[-500:]}"
            )
        if resultat.get("is_error"):
            raise ErreurModele(f"Claude Code : {resultat.get('result')}")

        usage = resultat.get("usage") or {}
        modeles = resultat.get("modelUsage") or {}
        # Claude Code peut appeler un petit modèle annexe : on garde celui qui a le plus écrit.
        modele_reel = max(
            modeles, key=lambda m: modeles[m].get("outputTokens", 0), default=self.modele
        )
        return ReponseModele(
            texte=resultat.get("result") or "",
            modele=modele_reel,
            duree_s=duree,
            cout_usd=resultat.get("total_cost_usd"),
            tokens_entree=(usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0),
            tokens_sortie=usage.get("output_tokens"),
            brut={"usage": usage, "modelUsage": modeles},
        )
