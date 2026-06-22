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
