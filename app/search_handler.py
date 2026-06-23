from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import Config
from app.searxng_client import RawHit

SearchFn = Callable[[str, int, "str | None"], Awaitable[list[RawHit]]]
ScrapeFn = Callable[[str], Awaitable[str]]


@dataclass
class SearchRequest:
    query: str
    max_results: int
    search_depth: str
    country: str | None


@dataclass
class ResultItem:
    title: str
    url: str
    content: str
    score: float


async def handle_search(
    req: SearchRequest,
    config: Config,
    *,
    search_fn: SearchFn,
    scrape_fn: ScrapeFn,
) -> list[ResultItem]:
    # search_depth : "advanced" récupère plus de candidats (≈2×, plafonné à 50) avant scraping
    # — découverte plus exhaustive ; "basic" (défaut) reste économe.
    n = min(req.max_results * 2, 50) if req.search_depth == "advanced" else req.max_results
    hits = await search_fn(req.query, n, req.country)
    if not hits:
        return []

    semaphore = asyncio.Semaphore(config.scrape_concurrency)

    async def scrape_one(hit: RawHit) -> str:
        async with semaphore:
            try:
                return await scrape_fn(hit.url)
            except Exception:
                return ""

    contents = await asyncio.gather(*(scrape_one(h) for h in hits))

    return [
        ResultItem(
            title=hit.title,
            url=hit.url,
            content=content or hit.snippet,
            score=hit.score,
        )
        for hit, content in zip(hits, contents)
    ]
