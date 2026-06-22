import os

from fastapi.testclient import TestClient

from app.searxng_client import RawHit
from app.server import app, get_scrape_fn, get_search_fn


def test_health():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_returns_tavily_shape():
    async def fake_search(query, max_results, country):
        return [RawHit("A", "https://a.fr", "snippet a", 0.9)]

    async def fake_scrape(url):
        return "contenu complet a"

    app.dependency_overrides[get_search_fn] = lambda: fake_search
    app.dependency_overrides[get_scrape_fn] = lambda: fake_scrape
    try:
        with TestClient(app) as client:
            resp = client.post("/search", json={"query": "q", "max_results": 5})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"results": [
        {"title": "A", "url": "https://a.fr", "content": "contenu complet a", "score": 0.9}
    ]}


def test_search_internal_error_returns_empty_results():
    async def boom_search(query, max_results, country):
        raise RuntimeError("searxng down")

    async def fake_scrape(url):
        return ""

    app.dependency_overrides[get_search_fn] = lambda: boom_search
    app.dependency_overrides[get_scrape_fn] = lambda: fake_scrape
    try:
        with TestClient(app) as client:
            resp = client.post("/search", json={"query": "q"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_auth_required_when_token_set(monkeypatch):
    monkeypatch.setenv("LOCAL_SEARCH_TOKEN", "secret")

    async def fake_search(query, max_results, country):
        return []

    async def fake_scrape(url):
        return ""

    app.dependency_overrides[get_search_fn] = lambda: fake_search
    app.dependency_overrides[get_scrape_fn] = lambda: fake_scrape
    try:
        with TestClient(app) as client:
            unauth = client.post("/search", json={"query": "q"})
            authed = client.post(
                "/search", json={"query": "q"},
                headers={"Authorization": "Bearer secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert unauth.status_code == 401
    assert authed.status_code == 200
