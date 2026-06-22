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
    readability_succeeded = False
    # 2. repli readability si trafilatura ramène trop peu.
    if len(extracted) < _MIN_USEFUL:
        try:
            summary_html = Document(html).summary()
            readability_text = _regex_clean(summary_html)
            # Prefer readability if it produced non-empty output (DOM-aware extraction)
            if readability_text:
                extracted = readability_text
                readability_succeeded = True
        except Exception:
            pass
    # 3. dernier repli : nettoyage regex brut (only if readability didn't succeed).
    if len(extracted) < _MIN_USEFUL and not readability_succeeded:
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
