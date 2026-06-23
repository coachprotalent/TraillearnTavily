from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass

import httpx


def _fold_accents(text: str) -> str:
    """Replie les accents (é→e, à→a…). L'instance SearXNG renvoie 0 résultat sur les
    requêtes accentuées (« université » → 0, « universite » → résultats) ; les moteurs
    sont de toute façon insensibles aux accents. Indispensable pour les requêtes FR."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )

# Mapping nom-de-pays (anglais minuscule, comme passé par Traillearn) -> langue SearXNG.
# SearXNG biaise la LANGUE, pas le pays : ce mapping ne suffit donc PAS à cibler un pays
# (cameroon et france donnent tous deux "fr"). Le vrai biais géographique est obtenu en
# injectant le nom du pays dans la requête (voir search_searxng) ; la langue reste un bonus.
_DEFAULT_COUNTRY_TO_LANGUAGE: dict[str, str] = {
    "france": "fr",
    "cameroon": "fr",
    "canada": "fr",
    "belgium": "fr",
    "senegal": "fr",
    "ivory coast": "fr",
    "morocco": "fr",
    "tunisia": "fr",
    "united kingdom": "en",
    "united states": "en",
    "nigeria": "en",
    "ghana": "en",
    "kenya": "en",
    "germany": "de",
    "spain": "es",
    "italy": "it",
    "portugal": "pt",
}


def _load_country_to_language(env: dict[str, str] | None = None) -> dict[str, str]:
    """Map pays->langue : défauts + surcharges via env SEARCH_COUNTRY_LANGUAGE.

    Format de la surcharge : "cameroon=fr,nigeria=en,brazil=pt" (séparateur virgule,
    clé=valeur). Permet d'étendre/corriger le mapping SANS redéployer le code.
    """
    e = env if env is not None else os.environ
    mapping = dict(_DEFAULT_COUNTRY_TO_LANGUAGE)
    raw = (e.get("SEARCH_COUNTRY_LANGUAGE") or "").strip()
    if raw:
        for pair in raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                k, v = k.strip().lower(), v.strip().lower()
                if k and v:
                    mapping[k] = v
    return mapping


_COUNTRY_TO_LANGUAGE: dict[str, str] = _load_country_to_language()


def _load_engines(env: dict[str, str] | None = None) -> str:
    """Liste de moteurs SearXNG à forcer (env SEARXNG_ENGINES, ex. "google,brave,startpage").

    Vide = comportement par défaut de SearXNG (tous les moteurs de la catégorie). Permet de
    privilégier les moteurs FIABLES (et d'écarter ceux fréquemment bloqués : CAPTCHA/429)
    sans éditer settings.yml ni redéployer le code."""
    e = env if env is not None else os.environ
    return (e.get("SEARXNG_ENGINES") or "").strip()


_ENGINES: str = _load_engines()

# Réessais sur erreur TRANSITOIRE de l'appel à SearXNG (timeout / 5xx / réseau).
_MAX_ATTEMPTS = 2


@dataclass
class RawHit:
    title: str
    url: str
    snippet: str
    score: float


async def search_searxng(
    client: httpx.AsyncClient,
    searxng_url: str,
    query: str,
    max_results: int,
    country: str | None,
) -> list[RawHit]:
    # Biais géographique : le nom du pays est ajouté aux TERMES de la requête (lever le plus
    # fiable avec SearXNG, qui n'a pas de vrai paramètre "pays"). La langue est un bonus.
    effective_query = query
    params: dict[str, str] = {"format": "json"}
    if country and country.strip():
        c = country.strip()
        if c.lower() not in query.lower():
            effective_query = f"{query} {c}"
        language = _COUNTRY_TO_LANGUAGE.get(c.lower())
        if language:
            params["language"] = language
    # SearXNG ne renvoie rien sur les accents → on les replie (moteurs insensibles aux accents).
    params["q"] = _fold_accents(effective_query)
    # Moteurs fiables forcés (env SEARXNG_ENGINES) pour écarter ceux fréquemment bloqués.
    if _ENGINES:
        params["engines"] = _ENGINES

    data = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await client.get(f"{searxng_url.rstrip('/')}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            break
        except ValueError:
            return []  # JSON invalide : pas de réessai
        except httpx.HTTPError:
            if attempt + 1 >= _MAX_ATTEMPTS:
                return []  # erreur transitoire persistante → vide
            continue       # réessai
    if data is None:
        return []

    raw_results = data.get("results", []) if isinstance(data, dict) else []
    hits: list[RawHit] = []
    total = len(raw_results)
    for i, r in enumerate(raw_results):
        url = r.get("url")
        if not isinstance(url, str) or not url:
            continue
        score = r.get("score")
        if not isinstance(score, (int, float)):
            score = 1.0 - (i / total) if total else 1.0
        hits.append(RawHit(
            title=r.get("title") or "",
            url=url,
            snippet=r.get("content") or "",
            score=float(score),
        ))
        if len(hits) >= max_results:
            break
    return hits
