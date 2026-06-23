import asyncio

from app.config import load_config
from app.searxng_client import RawHit
from app.search_handler import ResultItem, SearchRequest, handle_search


def _cfg(**over):
    env = {str(k).upper(): str(v) for k, v in over.items()}
    return load_config(env)


async def test_search_depth_advanced_fetches_more_candidates():
    seen = {}

    async def search_fn(query, max_results, country):
        seen["n"] = max_results
        return []

    async def scrape_fn(url):
        return ""

    # basic : n = max_results ; advanced : n ≈ 2× (plafonné à 50).
    req_basic = SearchRequest(query="q", max_results=10, search_depth="basic", country=None)
    await handle_search(req_basic, _cfg(), search_fn=search_fn, scrape_fn=scrape_fn)
    assert seen["n"] == 10

    req_adv = SearchRequest(query="q", max_results=10, search_depth="advanced", country=None)
    await handle_search(req_adv, _cfg(), search_fn=search_fn, scrape_fn=scrape_fn)
    assert seen["n"] == 20


async def test_content_from_scrape_then_fallback_to_snippet():
    hits = [
        RawHit("A", "https://a.fr", "snippet a", 0.9),
        RawHit("B", "https://b.fr", "snippet b", 0.5),
    ]

    async def search_fn(query, max_results, country):
        return hits

    async def scrape_fn(url):
        return "contenu complet a" if url == "https://a.fr" else ""

    req = SearchRequest(query="q", max_results=10, search_depth="basic", country=None)
    results = await handle_search(req, _cfg(), search_fn=search_fn, scrape_fn=scrape_fn)

    assert results == [
        ResultItem("A", "https://a.fr", "contenu complet a", 0.9),
        ResultItem("B", "https://b.fr", "snippet b", 0.5),  # repli snippet
    ]


async def test_respects_concurrency_limit():
    hits = [RawHit(f"T{i}", f"https://{i}.fr", "s", 0.5) for i in range(10)]
    active = 0
    peak = 0

    async def search_fn(query, max_results, country):
        return hits

    async def scrape_fn(url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "x"

    req = SearchRequest(query="q", max_results=10, search_depth="basic", country=None)
    await handle_search(req, _cfg(scrape_concurrency=3), search_fn=search_fn, scrape_fn=scrape_fn)

    assert peak <= 3


async def test_empty_when_no_hits():
    async def search_fn(query, max_results, country):
        return []

    async def scrape_fn(url):
        return "should not be called"

    req = SearchRequest(query="q", max_results=10, search_depth="basic", country=None)
    results = await handle_search(req, _cfg(), search_fn=search_fn, scrape_fn=scrape_fn)
    assert results == []
