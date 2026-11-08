"""Accès aux fournisseurs qui exposent une API au format OpenAI (OpenRouter, Nous Research…)."""

import base64
import time

import httpx

from generateur_devis.llm.base import ErreurModele, Image, ReponseModele


class OpenAICompatible:
    def __init__(
        self,
        fournisseur: str,
        url_base: str,
        cle_api: str,
        modele: str,
        timeout_s: float = 300,
        options: dict | None = None,
    ):
        if not cle_api:
            raise ErreurModele(f"{fournisseur} : clé d'API manquante (voir .env.example)")
        self.fournisseur = fournisseur
        self.url_base = url_base.rstrip("/")
        self.cle_api = cle_api
        self.modele = modele
        self.timeout_s = timeout_s
        self.options = options or {}
        self.nom = f"{fournisseur}:{modele}"

    def generer(
        self, prompt_systeme: str, prompt_utilisateur: str, images: list[Image]
    ) -> ReponseModele:
        contenu: list[dict] = [{"type": "text", "text": prompt_utilisateur}]
        for image in images:
            donnees = base64.b64encode(image.donnees).decode()
            contenu.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.type_mime};base64,{donnees}"},
                }
            )
        corps = {
            "model": self.modele,
            "messages": [
                {"role": "system", "content": prompt_systeme},
                {"role": "user", "content": contenu},
            ],
            "temperature": 0,
            **self.options,
        }

        debut = time.monotonic()
        try:
            reponse = httpx.post(
                f"{self.url_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.cle_api}"},
                json=corps,
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as e:
            raise ErreurModele(f"{self.fournisseur} : erreur réseau : {e}") from e
        duree = time.monotonic() - debut

        if reponse.status_code != 200:
            raise ErreurModele(
                f"{self.fournisseur} : HTTP {reponse.status_code} : {reponse.text[:500]}"
            )
        donnees = reponse.json()
        if "error" in donnees:
            raise ErreurModele(f"{self.fournisseur} : {donnees['error']}")
        try:
            texte = donnees["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise ErreurModele(f"{self.fournisseur} : réponse inattendue : {donnees}") from e

        usage = donnees.get("usage") or {}
        return ReponseModele(
            texte=texte,
            modele=donnees.get("model", self.modele),
            duree_s=duree,
            cout_usd=usage.get("cost"),  # fourni par OpenRouter
            tokens_entree=usage.get("prompt_tokens"),
            tokens_sortie=usage.get("completion_tokens"),
            brut={"usage": usage, "id": donnees.get("id")},
        )
