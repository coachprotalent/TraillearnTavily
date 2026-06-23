import httpx

import app.scraper as scraper
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


async def test_fetch_and_extract_handles_pdf(monkeypatch):
    # Un PDF (guide d'admission) est désormais accepté et son texte extrait.
    monkeypatch.setattr(scraper, "extract_pdf_text", lambda content, max_chars: "TEXTE PDF EXTRAIT")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 ...")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_and_extract(client, "https://x.fr/guide.pdf", 15000, 20000)

    assert text == "TEXTE PDF EXTRAIT"


async def test_fetch_and_extract_returns_empty_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_and_extract(client, "https://x.fr", 15000, 20000)

    assert text == ""
