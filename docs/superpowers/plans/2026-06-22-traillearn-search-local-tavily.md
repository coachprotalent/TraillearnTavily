# Traillearn Search (Tavily local) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un service HTTP autonome, compatible avec l'API Tavily, qui s'appuie sur SearXNG (auto-hébergé) + scraping, pour remplacer Tavily à coût quasi nul dans le projet Traillearn.

**Architecture :** Un service FastAPI (`TraillearnTavily/`) reçoit `POST /search` au format Tavily, interroge SearXNG (méta-moteur en Docker), scrape en parallèle le contenu principal de chaque URL via `trafilatura`, et renvoie `{results:[{title,url,content,score}]}`. Le backend Traillearn pointe simplement `TAVILY_URL` vers ce service ; tout le reste (cache Redis, retry, métriques) est inchangé.

**Tech Stack :** Python 3.12, FastAPI, uvicorn, httpx (async), trafilatura, readability-lxml, lxml, pydantic ; tests pytest + pytest-asyncio ; Docker + docker-compose ; côté Traillearn : TypeScript (modif d'1 fichier).

## Global Constraints

- Python **3.12** minimum.
- Format de réponse strictement compatible Tavily : `{ "results": [ { "title": str, "url": str, "content": str, "score": float } ] }`. Toute réponse de succès = HTTP `200`. Toute erreur interne = HTTP `200` avec `{"results": []}`.
- Le service ne reproduit **pas** les codes 429/432 (spécifiques au quota Tavily).
- Tous les paramètres réglables passent par variables d'environnement avec valeurs par défaut (cf. spec §7) : `SEARXNG_URL` (`http://searxng:8080`), `SERVICE_PORT` (`8088`), `LOCAL_SEARCH_TOKEN` (vide), `SCRAPE_CONCURRENCY` (`5`), `SCRAPE_FETCH_TIMEOUT_MS` (`15000`), `SCRAPE_MAX_CHARS` (`20000`), `SCRAPE_ALLOW_INSECURE_TLS` (`true`).
- TDD : pour chaque module, test d'abord (qui échoue), puis implémentation minimale, puis test vert, puis commit.
- Aucun port exposé publiquement : le service écoute sur `127.0.0.1:8088`, SearXNG reste interne au réseau Docker.
- Spec de référence : `docs/superpowers/specs/2026-06-22-traillearn-search-local-tavily-design.md`.

## File Structure

```
TraillearnTavily/
├── pyproject.toml                 # métadonnées projet + deps + config pytest
├── requirements.txt               # deps runtime (pour le Dockerfile)
├── Dockerfile                     # image du service Python
├── docker-compose.yml             # searxng + traillearn-search
├── .env.example                   # variables d'env documentées
├── searxng/
│   └── settings.yml               # config SearXNG (active le format json)
├── app/
│   ├── __init__.py
│   ├── config.py                  # Config + load_config(env)
│   ├── searxng_client.py          # RawHit + search_searxng(...)
│   ├── scraper.py                 # fetch_html, extract_main_text, fetch_and_extract
│   ├── search_handler.py          # SearchRequest, ResultItem, handle_search(...)
│   └── server.py                  # app FastAPI : POST /search, GET /health
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_searxng_client.py
    ├── test_scraper.py
    ├── test_search_handler.py
    └── test_server.py
```

Côté Traillearn (dépôt sibling `../Traillearn`) :
```
apps/backend/src/services/tavily/tavily-client.ts        # baseUrl configurable
apps/backend/src/services/tavily/tavily-client.test.ts   # +1 test
```

---

### Task 1: Scaffold projet + configuration

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py` (vide)
- Create: `tests/__init__.py` (vide)
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `class Config` (dataclass) avec champs : `searxng_url: str`, `service_port: int`, `local_search_token: str | None`, `scrape_concurrency: int`, `scrape_fetch_timeout_ms: int`, `scrape_max_chars: int`, `scrape_allow_insecure_tls: bool`.
  - `def load_config(env: Mapping[str, str] | None = None) -> Config` — lit les variables d'env (défaut `os.environ`), applique les valeurs par défaut, parse entiers/booléens de façon tolérante.

- [ ] **Step 1: Créer `pyproject.toml`**

```toml
[project]
name = "traillearn-search"
version = "0.1.0"
description = "Service de recherche web local compatible Tavily (SearXNG + scraping)"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "httpx>=0.27",
    "trafilatura>=1.8",
    "readability-lxml>=0.8.1",
    "lxml>=5.0",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Créer `requirements.txt`**

```text
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
trafilatura>=1.8
readability-lxml>=0.8.1
lxml>=5.0
pydantic>=2.6
```

- [ ] **Step 3: Créer `.env.example`**

```text
# URL interne de SearXNG (réseau Docker)
SEARXNG_URL=http://searxng:8080
# Port d'écoute du service
SERVICE_PORT=8088
# Si défini, exige ce Bearer ; sinon auth ignorée (service lié à 127.0.0.1)
LOCAL_SEARCH_TOKEN=
# Pages scrapées en parallèle par requête
SCRAPE_CONCURRENCY=5
# Timeout fetch par page (ms)
SCRAPE_FETCH_TIMEOUT_MS=15000
# Troncature du contenu extrait (caractères)
SCRAPE_MAX_CHARS=20000
# Tolérance certificats TLS invalides au scraping
SCRAPE_ALLOW_INSECURE_TLS=true
```

- [ ] **Step 4: Créer les fichiers vides `app/__init__.py` et `tests/__init__.py`**

Les deux fichiers sont vides (marqueurs de package).

- [ ] **Step 5: Écrire le test qui échoue — `tests/test_config.py`**

```python
from app.config import load_config


def test_defaults_when_env_empty():
    cfg = load_config({})
    assert cfg.searxng_url == "http://searxng:8080"
    assert cfg.service_port == 8088
    assert cfg.local_search_token is None
    assert cfg.scrape_concurrency == 5
    assert cfg.scrape_fetch_timeout_ms == 15000
    assert cfg.scrape_max_chars == 20000
    assert cfg.scrape_allow_insecure_tls is True


def test_overrides_from_env():
    cfg = load_config({
        "SEARXNG_URL": "http://127.0.0.1:9090",
        "SERVICE_PORT": "8088",
        "LOCAL_SEARCH_TOKEN": "secret",
        "SCRAPE_CONCURRENCY": "3",
        "SCRAPE_ALLOW_INSECURE_TLS": "false",
    })
    assert cfg.searxng_url == "http://127.0.0.1:9090"
    assert cfg.local_search_token == "secret"
    assert cfg.scrape_concurrency == 3
    assert cfg.scrape_allow_insecure_tls is False


def test_invalid_int_falls_back_to_default():
    cfg = load_config({"SCRAPE_CONCURRENCY": "abc"})
    assert cfg.scrape_concurrency == 5
```

- [ ] **Step 6: Lancer le test — il doit échouer**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.config'`)

- [ ] **Step 7: Implémenter `app/config.py`**

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    searxng_url: str
    service_port: int
    local_search_token: str | None
    scrape_concurrency: int
    scrape_fetch_timeout_ms: int
    scrape_max_chars: int
    scrape_allow_insecure_tls: bool


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() != "false"


def load_config(env: Mapping[str, str] | None = None) -> Config:
    e = env if env is not None else os.environ
    token = e.get("LOCAL_SEARCH_TOKEN") or None
    return Config(
        searxng_url=e.get("SEARXNG_URL", "http://searxng:8080"),
        service_port=_int(e, "SERVICE_PORT", 8088),
        local_search_token=token,
        scrape_concurrency=_int(e, "SCRAPE_CONCURRENCY", 5),
        scrape_fetch_timeout_ms=_int(e, "SCRAPE_FETCH_TIMEOUT_MS", 15000),
        scrape_max_chars=_int(e, "SCRAPE_MAX_CHARS", 20000),
        scrape_allow_insecure_tls=_bool(e, "SCRAPE_ALLOW_INSECURE_TLS", True),
    )
```

- [ ] **Step 8: Lancer le test — il doit passer**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml requirements.txt .env.example app/__init__.py app/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: scaffold projet + config par variables d'env"
```

---

### Task 2: Client SearXNG

**Files:**
- Create: `app/searxng_client.py`
- Test: `tests/test_searxng_client.py`

**Interfaces:**
- Consumes: rien (reçoit un `httpx.AsyncClient` injecté).
- Produces:
  - `@dataclass class RawHit` : `title: str`, `url: str`, `snippet: str`, `score: float`.
  - `async def search_searxng(client: httpx.AsyncClient, searxng_url: str, query: str, max_results: int, country: str | None) -> list[RawHit]`
    - Appelle `GET {searxng_url}/search` avec params `q`, `format=json`, et `language` si `country` est mappable.
    - Mappe chaque résultat JSON (`title`, `url`, `content`, `score`) vers `RawHit` (snippet = `content` SearXNG). Score absent → dérivé du rang : `1.0 - i/len`.
    - Ignore les entrées sans `url`. Tronque à `max_results`.

- [ ] **Step 1: Écrire le test qui échoue — `tests/test_searxng_client.py`**

```python
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


async def test_searxng_error_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    async with _client(handler) as client:
        hits = await search_searxng(client, "http://searxng:8080", "q", 5, None)

    assert hits == []
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `python -m pytest tests/test_searxng_client.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.searxng_client'`)

- [ ] **Step 3: Implémenter `app/searxng_client.py`**

```python
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
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run: `python -m pytest tests/test_searxng_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/searxng_client.py tests/test_searxng_client.py
git commit -m "feat: client SearXNG (parsing JSON + mapping pays->langue)"
```

---

### Task 3: Scraper (fetch + extraction du contenu principal)

**Files:**
- Create: `app/scraper.py`
- Test: `tests/test_scraper.py`

**Interfaces:**
- Consumes: rien (reçoit un `httpx.AsyncClient`).
- Produces:
  - `def extract_main_text(html: str, max_chars: int) -> str` — extrait l'article principal (`trafilatura` → repli `readability-lxml` → repli nettoyage regex), tronque à `max_chars`.
  - `async def fetch_html(client: httpx.AsyncClient, url: str, timeout_ms: int) -> tuple[bool, str, int]` — `(ok, html, status)`. Refuse les Content-Type non-HTML et les corps > 2 Mo (Content-Length).
  - `async def fetch_and_extract(client: httpx.AsyncClient, url: str, timeout_ms: int, max_chars: int) -> str` — `""` si échec.

- [ ] **Step 1: Écrire le test qui échoue — `tests/test_scraper.py`**

```python
import httpx

from app.scraper import extract_main_text, fetch_html, fetch_and_extract


def test_extract_main_text_strips_chrome():
    html = """
    <html><body>
      <nav>menu accueil contact</nav>
      <article><p>Le coût de la formation est de 11 850 euros par an.</p>
      <p>Les bourses couvrent jusqu'à 50% des frais.</p></article>
      <footer>tous droits réservés</footer>
    </body></html>
    """
    text = extract_main_text(html, 20000)
    assert "11 850 euros par an" in text
    assert "tous droits réservés" not in text


def test_extract_main_text_truncates():
    html = "<html><body><article><p>" + ("a" * 5000) + "</p></article></body></html>"
    text = extract_main_text(html, 100)
    assert len(text) == 100


def test_extract_main_text_regex_fallback_on_empty():
    # Pas d'article identifiable : on retombe sur un nettoyage basique non vide.
    html = "<html><body>texte brut sans structure</body></html>"
    text = extract_main_text(html, 20000)
    assert "texte brut sans structure" in text


async def test_fetch_html_rejects_non_html():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok, html, status = await fetch_html(client, "https://x.fr/doc.pdf", 15000)

    assert ok is False
    assert html == ""


async def test_fetch_and_extract_happy_path():
    page = "<html><body><article><p>Frais: 11 850 euros</p></article></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=page)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_and_extract(client, "https://x.fr", 15000, 20000)

    assert "11 850 euros" in text


async def test_fetch_and_extract_returns_empty_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_and_extract(client, "https://x.fr", 15000, 20000)

    assert text == ""
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `python -m pytest tests/test_scraper.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.scraper'`)

- [ ] **Step 3: Implémenter `app/scraper.py`**

```python
from __future__ import annotations

import re

import httpx
import trafilatura
from readability import Document

_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 Mo
_MIN_USEFUL = 200

# En-têtes navigateur pour limiter les blocages basiques.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr,en;q=0.8",
}


def _regex_clean(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&#39;": "'", "&apos;": "'", "&quot;": '"',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", " ", text).strip()


def extract_main_text(html: str, max_chars: int) -> str:
    # 1. trafilatura — meilleure extraction d'article.
    extracted = trafilatura.extract(html) or ""
    # 2. repli readability si trafilatura ramène trop peu.
    if len(extracted) < _MIN_USEFUL:
        try:
            summary_html = Document(html).summary()
            readability_text = _regex_clean(summary_html)
        except Exception:
            readability_text = ""
        if len(readability_text) > len(extracted):
            extracted = readability_text
    # 3. dernier repli : nettoyage regex brut.
    if len(extracted) < _MIN_USEFUL:
        regex_text = _regex_clean(html)
        if len(regex_text) > len(extracted):
            extracted = regex_text
    return extracted[:max_chars]


async def fetch_html(
    client: httpx.AsyncClient, url: str, timeout_ms: int
) -> tuple[bool, str, int]:
    try:
        resp = await client.get(
            url,
            headers=_BROWSER_HEADERS,
            timeout=timeout_ms / 1000,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return (False, "", 0)

    if resp.status_code >= 400:
        return (False, "", resp.status_code)

    content_type = (resp.headers.get("content-type") or "").lower()
    if content_type and not any(content_type.startswith(t) for t in _ALLOWED_CONTENT_TYPES):
        return (False, "", resp.status_code)

    content_length = resp.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                return (False, "", resp.status_code)
        except ValueError:
            pass

    return (True, resp.text, resp.status_code)


async def fetch_and_extract(
    client: httpx.AsyncClient, url: str, timeout_ms: int, max_chars: int
) -> str:
    ok, html, _status = await fetch_html(client, url, timeout_ms)
    if not ok or not html:
        return ""
    return extract_main_text(html, max_chars)
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run: `python -m pytest tests/test_scraper.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py tests/test_scraper.py
git commit -m "feat: scraper (fetch tolérant + extraction trafilatura/readability/regex)"
```

---

### Task 4: Orchestration (search_handler)

**Files:**
- Create: `app/search_handler.py`
- Test: `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `RawHit` (Task 2), `Config` (Task 1).
- Produces:
  - `@dataclass class SearchRequest` : `query: str`, `max_results: int`, `search_depth: str`, `country: str | None`.
  - `@dataclass class ResultItem` : `title: str`, `url: str`, `content: str`, `score: float`.
  - `async def handle_search(req: SearchRequest, config: Config, *, search_fn, scrape_fn) -> list[ResultItem]`
    - `search_fn(query: str, max_results: int, country: str | None) -> Awaitable[list[RawHit]]`
    - `scrape_fn(url: str) -> Awaitable[str]`
    - Scrape borné par `asyncio.Semaphore(config.scrape_concurrency)`. `content` = texte scrapé, repli sur `hit.snippet` si vide. Préserve l'ordre SearXNG.

- [ ] **Step 1: Écrire le test qui échoue — `tests/test_search_handler.py`**

```python
import asyncio

from app.config import load_config
from app.searxng_client import RawHit
from app.search_handler import ResultItem, SearchRequest, handle_search


def _cfg(**over):
    env = {str(k).upper(): str(v) for k, v in over.items()}
    return load_config(env)


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
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `python -m pytest tests/test_search_handler.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.search_handler'`)

- [ ] **Step 3: Implémenter `app/search_handler.py`**

```python
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
    hits = await search_fn(req.query, req.max_results, req.country)
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
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run: `python -m pytest tests/test_search_handler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/search_handler.py tests/test_search_handler.py
git commit -m "feat: orchestration recherche (scrape parallèle borné + repli snippet)"
```

---

### Task 5: Serveur FastAPI (endpoints + auth)

**Files:**
- Create: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `search_searxng` (Task 2), `fetch_and_extract` (Task 3), `handle_search`/`SearchRequest`/`ResultItem` (Task 4).
- Produces:
  - `app` : instance FastAPI.
  - `POST /search` (corps Pydantic `SearchBody`) → `{"results": [...]}` au format Tavily ; `200` même en cas d'erreur interne (`{"results": []}`).
  - `GET /health` → `{"status": "ok"}`.
  - Dépendances surchargeables en test : `get_search_fn`, `get_scrape_fn`.

- [ ] **Step 1: Écrire le test qui échoue — `tests/test_server.py`**

```python
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
```

- [ ] **Step 2: Lancer le test — il doit échouer**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.server'`)

- [ ] **Step 3: Implémenter `app/server.py`**

```python
from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Config, load_config
from app.scraper import fetch_and_extract
from app.search_handler import SearchRequest, handle_search
from app.searxng_client import search_searxng


class SearchBody(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=50)
    search_depth: str = Field(default="basic")
    country: str | None = Field(default=None)


class ResultModel(BaseModel):
    title: str
    url: str
    content: str
    score: float


class SearchResponse(BaseModel):
    results: list[ResultModel]


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    app.state.config = cfg
    app.state.http = httpx.AsyncClient(
        verify=not cfg.scrape_allow_insecure_tls,
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(lifespan=lifespan)


def get_config() -> Config:
    return app.state.config


# Dépendances injectables (surchargées en test via app.dependency_overrides).
def get_search_fn():
    async def _fn(query: str, max_results: int, country: str | None):
        cfg: Config = app.state.config
        return await search_searxng(
            app.state.http, cfg.searxng_url, query, max_results, country
        )
    return _fn


def get_scrape_fn():
    async def _fn(url: str):
        cfg: Config = app.state.config
        return await fetch_and_extract(
            app.state.http, url, cfg.scrape_fetch_timeout_ms, cfg.scrape_max_chars
        )
    return _fn


def _check_auth(cfg: Config, authorization: str | None) -> None:
    if not cfg.local_search_token:
        return
    expected = f"Bearer {cfg.local_search_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search(
    body: SearchBody,
    authorization: str | None = Header(default=None),
    cfg: Config = Depends(get_config),
    search_fn=Depends(get_search_fn),
    scrape_fn=Depends(get_scrape_fn),
) -> SearchResponse:
    _check_auth(cfg, authorization)
    req = SearchRequest(
        query=body.query,
        max_results=body.max_results,
        search_depth=body.search_depth,
        country=body.country,
    )
    try:
        items = await handle_search(req, cfg, search_fn=search_fn, scrape_fn=scrape_fn)
    except Exception:
        return SearchResponse(results=[])
    return SearchResponse(
        results=[ResultModel(title=i.title, url=i.url, content=i.content, score=i.score) for i in items]
    )


def main() -> None:
    import uvicorn

    cfg = load_config()
    uvicorn.run(app, host="0.0.0.0", port=cfg.service_port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lancer toute la suite**

Run: `python -m pytest -v`
Expected: PASS (tous les tests des tâches 1-5)

- [ ] **Step 6: Commit**

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: serveur FastAPI (/search format Tavily, /health, auth Bearer)"
```

---

### Task 6: Conteneurisation (Dockerfile + docker-compose + SearXNG)

**Files:**
- Create: `Dockerfile`
- Create: `searxng/settings.yml`
- Create: `docker-compose.yml`
- Modify: `.env.example` (ajout note de démarrage — déjà créé en Task 1)

**Interfaces:**
- Consumes: `app/server.py:main` (Task 5).
- Produces: stack Docker démarrable (`docker compose up`) exposant le service sur `127.0.0.1:8088`.

- [ ] **Step 1: Créer `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /service

# Dépendances système pour lxml/trafilatura (libxml2/libxslt).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV SERVICE_PORT=8088
EXPOSE 8088

CMD ["python", "-m", "app.server"]
```

- [ ] **Step 2: Créer `searxng/settings.yml`**

```yaml
# Configuration minimale SearXNG : active la sortie JSON (indispensable pour l'API).
# `secret_key` DOIT être remplacée par une valeur aléatoire en production.
use_default_settings: true

server:
  secret_key: "change-me-in-production"
  limiter: false
  image_proxy: false

search:
  formats:
    - html
    - json
```

- [ ] **Step 3: Créer `docker-compose.yml`**

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    restart: unless-stopped
    volumes:
      - ./searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8080/
    # Pas de ports exposés : accessible uniquement via le réseau interne Docker.

  traillearn-search:
    build: .
    restart: unless-stopped
    depends_on:
      - searxng
    environment:
      - SEARXNG_URL=http://searxng:8080
      - SERVICE_PORT=8088
      - SCRAPE_CONCURRENCY=5
      - SCRAPE_FETCH_TIMEOUT_MS=15000
      - SCRAPE_MAX_CHARS=20000
      - SCRAPE_ALLOW_INSECURE_TLS=true
      # - LOCAL_SEARCH_TOKEN=   # décommenter pour exiger un Bearer
    ports:
      - "127.0.0.1:8088:8088"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8088/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

- [ ] **Step 4: Vérifier le build de l'image**

Run: `docker compose build traillearn-search`
Expected: build réussi sans erreur.

- [ ] **Step 5: Démarrer la stack et vérifier le health + une recherche réelle**

Run:
```bash
docker compose up -d
sleep 15
curl -s http://127.0.0.1:8088/health
curl -s -X POST http://127.0.0.1:8088/search -H "Content-Type: application/json" -d '{"query":"bourses études France","max_results":3}'
```
Expected: `{"status":"ok"}` puis un JSON `{"results":[...]}` avec au moins 1 résultat contenant `title`/`url`/`content`/`score`.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile searxng/settings.yml docker-compose.yml
git commit -m "feat: conteneurisation (Dockerfile + docker-compose searxng + service)"
```

---

### Task 7: Brancher Traillearn (TAVILY_URL configurable)

**Files:**
- Modify: `../Traillearn/apps/backend/src/services/tavily/tavily-client.ts:39` (et points d'usage de la constante)
- Test: `../Traillearn/apps/backend/src/services/tavily/tavily-client.test.ts`

**Interfaces:**
- Consumes: rien de nouveau ; ajoute un champ optionnel à `TavilyClientDeps`.
- Produces: `TavilyClient` qui appelle `deps.baseUrl ?? process.env.TAVILY_URL ?? "https://api.tavily.com/search"`.

- [ ] **Step 1: Écrire le test qui échoue — ajouter à `tavily-client.test.ts`**

```ts
test("search() utilise baseUrl injecté (override du endpoint Tavily)", async () => {
  let calledUrl = "";
  const fetchImpl = (async (url: string) => {
    calledUrl = url;
    return { ok: true, status: 200, json: async () => ({ results: [] }), text: async () => "" };
  }) as never;
  const c = new TavilyClient({
    fetchImpl,
    cache: memCache(),
    apiKey: "local-dummy",
    baseUrl: "http://127.0.0.1:8088/search"
  });
  await c.search("q", {});
  assert.equal(calledUrl, "http://127.0.0.1:8088/search");
});
```

> Note : `memCache()` est le helper déjà présent en haut de `tavily-client.test.ts` ; le réutiliser tel quel. Si `TavilyClientDeps` n'expose pas encore `baseUrl`, le test ne compilera pas → c'est l'échec attendu.

- [ ] **Step 2: Lancer le test — il doit échouer (compilation)**

Run (depuis `../Traillearn`): `npm test -w @traillearn/backend -- tavily-client`
Expected: FAIL — TypeScript : `baseUrl` n'existe pas sur `TavilyClientDeps`.

- [ ] **Step 3: Implémenter — modifier `tavily-client.ts`**

3a. Renommer la constante (ligne 39) :
```ts
const TAVILY_DEFAULT_URL = "https://api.tavily.com/search";
```

3b. Ajouter le champ à `TavilyClientDeps` (après `usage?: string;`) :
```ts
  /** URL de l'endpoint de recherche. Défaut : env TAVILY_URL puis l'API Tavily publique. */
  baseUrl?: string;
```

3c. Ajouter le champ privé et son init dans le constructeur (à côté de `this.usage = ...`) :
```ts
  private readonly baseUrl: string;
```
```ts
    this.baseUrl = deps?.baseUrl ?? process.env["TAVILY_URL"] ?? TAVILY_DEFAULT_URL;
```

3d. Remplacer l'appel `this.fetchImpl(TAVILY_URL, {` par :
```ts
          resp = await this.fetchImpl(this.baseUrl, {
```

- [ ] **Step 4: Lancer le test — il doit passer**

Run (depuis `../Traillearn`): `npm test -w @traillearn/backend -- tavily-client`
Expected: PASS (tests existants + le nouveau).

- [ ] **Step 5: Commit (dans le dépôt Traillearn)**

```bash
cd ../Traillearn
git add apps/backend/src/services/tavily/tavily-client.ts apps/backend/src/services/tavily/tavily-client.test.ts
git commit -m "feat(tavily): endpoint configurable via TAVILY_URL (support service local)"
```

- [ ] **Step 6: Documenter l'activation (configuration serveur)**

Ajouter à `/etc/traillearn/app.env` sur la VM (hors dépôt) :
```
TAVILY_URL=http://127.0.0.1:8088/search
TAVILY_API_KEY=local-dummy
```
Puis `pm2 reload ecosystem.config.cjs`. (Étape opérationnelle — pas de commit.)

---

## Self-Review

**Spec coverage :**
- §3 architecture → Tasks 2-6. §4 contrat HTTP → Task 5. §5 composants → Tasks 1-5 (1:1). §6 changements Traillearn → Task 7. §7 env → Task 1. §8 déploiement → Task 6. §9 résilience → Tasks 3 (repli scrape), 4 (concurrence/repli snippet), 5 (200 sur erreur). §10 tests → chaque tâche. §11 hors-périmètre → respecté (pas de cache interne, pas de Playwright, pas de fallback Tavily). ✅ Aucune lacune.

**Placeholder scan :** aucun TBD/TODO ; tout code de step est complet. ✅

**Type consistency :** `RawHit(title,url,snippet,score)` cohérent Tasks 2/4/5. `ResultItem(title,url,content,score)` cohérent Tasks 4/5. `handle_search(req, config, *, search_fn, scrape_fn)` identique Tasks 4/5. `fetch_and_extract(client,url,timeout_ms,max_chars)` identique Tasks 3/5. `search_searxng(client,searxng_url,query,max_results,country)` identique Tasks 2/5. ✅
