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
