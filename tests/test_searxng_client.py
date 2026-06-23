import httpx
import pytest

from app.searxng_client import RawHit, search_searxng


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_parses_results_and_maps_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "bourses france"
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [
            {"title": "A", "url": "https://a.fr", "content": "snippet a", "score": 0.9},
            {"title": "B", "url": "https://b.fr", "content": "snippet b", "score": 0.5},
        ]})

    async with _client(handler) as client:
        hits = await search_searxng(client, "http://searxng:8080", "bourses france", 10, None)

    assert hits == [
        RawHit(title="A", url="https://a.fr", snippet="snippet a", score=0.9),
        RawHit(title="B", url="https://b.fr", snippet="snippet b", score=0.5),
    ]


async def test_truncates_to_max_results_and_skips_urlless():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"title": "A", "url": "https://a.fr", "content": "x"},
            {"title": "NoUrl", "content": "y"},
            {"title": "B", "url": "https://b.fr", "content": "z"},
        ]})

    async with _client(handler) as client:
        hits = await search_searxng(client, "http://searxng:8080", "q", 1, None)

    assert len(hits) == 1
    assert hits[0].url == "https://a.fr"
    # score dérivé du rang quand absent
    assert hits[0].score == 1.0


async def test_country_maps_to_language():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["language"] = request.url.params.get("language")
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await search_searxng(client, "http://searxng:8080", "q", 5, "france")

    assert seen["language"] == "fr"


async def test_query_accents_are_folded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await search_searxng(client, "http://searxng:8080", "écoles ingénieur", 5, None)

    # SearXNG renvoie 0 sur les accents → la requête envoyée est dépliée.
    assert seen["q"] == "ecoles ingenieur"


async def test_country_injected_into_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await search_searxng(client, "http://searxng:8080", "ecoles", 5, "cameroon")

    # Le nom du pays est ajouté aux termes (vrai biais géo), pas seulement la langue.
    assert "cameroon" in seen["q"].lower()


async def test_country_not_duplicated_if_already_in_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await search_searxng(client, "http://searxng:8080", "ecoles cameroon", 5, "cameroon")

    assert seen["q"].lower().count("cameroon") == 1


def test_country_language_map_env_override():
    from app.searxng_client import _load_country_to_language

    mapping = _load_country_to_language({"SEARCH_COUNTRY_LANGUAGE": "brazil=pt, cameroon=en"})
    assert mapping["brazil"] == "pt"
    assert mapping["cameroon"] == "en"  # surcharge le défaut "fr"
    assert mapping["france"] == "fr"     # défaut conservé


async def test_searxng_error_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    async with _client(handler) as client:
        hits = await search_searxng(client, "http://searxng:8080", "q", 5, None)

    assert hits == []
