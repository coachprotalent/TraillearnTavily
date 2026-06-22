from __future__ import annotations

from dataclasses import dataclass

import httpx

# Mapping minimal nom-de-pays (anglais minuscule, comme passé par Traillearn) -> langue SearXNG.
# Étendre au besoin ; un pays inconnu n'ajoute simplement aucun biais de langue.
_COUNTRY_TO_LANGUAGE: dict[str, str] = {
    "france": "fr",
    "cameroon": "fr",
    "canada": "fr",
    "belgium": "fr",
    "senegal": "fr",
    "united kingdom": "en",
    "united states": "en",
    "germany": "de",
    "spain": "es",
}


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
    params: dict[str, str] = {"q": query, "format": "json"}
    if country:
        language = _COUNTRY_TO_LANGUAGE.get(country.strip().lower())
        if language:
            params["language"] = language

    try:
        resp = await client.get(f"{searxng_url.rstrip('/')}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
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
