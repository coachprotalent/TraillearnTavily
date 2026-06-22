from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import Config, load_config
from app.scraper import fetch_and_extract
from app.search_handler import SearchRequest, handle_search
from app.searxng_client import search_searxng
from app.test_page import TEST_PAGE_HTML


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


@app.get("/", response_class=HTMLResponse)
async def test_page() -> str:
    """Banc de test graphique (même origine que /search → pas de CORS)."""
    return TEST_PAGE_HTML


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
    # host=0.0.0.0 est requis DANS le conteneur pour que le mapping de port Docker
    # fonctionne. L'exposition reste limitée à localhost par le compose
    # (`127.0.0.1:8088:8088`), pas par l'app. Hors Docker, restreindre via un reverse
    # proxy ou activer LOCAL_SEARCH_TOKEN.
    uvicorn.run(app, host="0.0.0.0", port=cfg.service_port)  # noqa: S104


if __name__ == "__main__":
    main()
