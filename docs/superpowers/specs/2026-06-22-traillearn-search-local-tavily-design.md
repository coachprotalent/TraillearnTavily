# Traillearn Search — service Tavily-compatible local

**Date :** 2026-06-22
**Statut :** Design validé (en attente de revue finale utilisateur)
**Objectif :** Remplacer l'API Tavily (facturée au crédit) par un service auto-hébergé,
compatible au format, pour réduire le coût à ~0 € par requête.

---

## 1. Contexte & motivation

Le projet `Traillearn` (sibling `../Traillearn`) utilise Tavily pour la recherche web à
travers un client unique `apps/backend/src/services/tavily/tavily-client.ts`. Tavily est
appelé à 3 endroits fonctionnels :

| Consommateur | Fichier | Usage du `content` |
|---|---|---|
| Découverte d'URLs | `data-ops/ai-discovery/ai-discovery-url-discovery.ts` | snippet (`content.slice(0,300)`) |
| Enrichissement | `enrichment/enrich-fill.ts` | contenu complet → LLM extrait des valeurs |
| Pivot pays DVP | `dvp/dvp-pivot-llm-fallback.ts` | contenu complet → LLM |

Le client est instancié via `new TavilyClient({ usage })` à ~4 endroits, tous dépendant
de la même signature :

```ts
search(query, { maxResults, searchDepth, country }):
  Promise<{ results: { title, url, content, score? }[], unavailable?: true }>
```

Tavily est facturé au crédit (basic = 1, advanced = 2). Le besoin : une alternative
locale, gratuite, sans dégrader la qualité.

## 2. Décisions (issues du brainstorming)

| Décision | Choix retenu |
|---|---|
| Source de recherche | **SearXNG** auto-hébergé à 100 % (méta-moteur agrégeant Google/Bing/DuckDuckGo) |
| Hébergement | **Même VM Azure** que le backend, en conteneurs Docker |
| Génération du `content` | **Scraping complet systématique** de chaque URL (qualité maximale partout) |
| Forme | **Service HTTP autonome** dans `TraillearnTavily/`, compatible API Tavily |
| Stack | **Python 3.12 + FastAPI + httpx (async) + trafilatura** |
| Extraction | **trafilatura** (extraction de l'article principal, équiv. Python de Readability) ; repli `readability-lxml` puis nettoyage regex |

## 3. Architecture

```
Traillearn (TavilyClient inchangé : cache Redis 7j + retry + round-robin + métriques)
   │  POST /search  {query, max_results, search_depth, country}  Bearer <token>
   ▼
TraillearnTavily/  service FastAPI (port 8088)
   ├─ 1. SearXNG  GET /search?q=...&format=json     → [{title, url, content(snippet), score}]
   ├─ 2. scrape chaque URL en parallèle (sémaphore) → contenu principal propre
   └─ 3. réponse {results:[{title,url,content,score}]}  ← format Tavily exact
   ▼
SearXNG (Docker, 127.0.0.1:8080) → Google / Bing / DuckDuckGo
```

Les deux services tournent dans un `docker-compose.yml` unique dans `TraillearnTavily/`.

## 4. Contrat HTTP (compatible Tavily)

**Requête** — `POST /search`
- Header : `Authorization: Bearer <token>` (validé contre `LOCAL_SEARCH_TOKEN` si défini ; sinon ignoré — service lié à 127.0.0.1)
- Corps :
  ```json
  { "query": "string", "max_results": 10, "search_depth": "basic|advanced", "country": "france" }
  ```

**Réponse** — `200 OK`
```json
{ "results": [ { "title": "...", "url": "...", "content": "...", "score": 0.93 } ] }
```

- Toujours `200` en cas de succès. On **ne reproduit pas** les codes 429/432 (spécifiques au
  quota Tavily, inutiles en local).
- Erreur interne (SearXNG injoignable, etc.) → `200` avec `{ "results": [] }`. Le
  `TavilyClient` traite déjà une liste vide comme `unavailable` (dégradation gracieuse).
- `GET /health` → `200 {"status":"ok"}` pour la supervision Docker.

## 5. Composants (isolés et testables)

Tous dans `TraillearnTavily/app/`.

### 5.1 `searxng_client.py`
- `async search_searxng(query, max_results, country) -> list[RawHit]`
- Appelle `GET {SEARXNG_URL}/search` avec `format=json`, `q`, et mappe `country` (nom
  anglais minuscule, ex. `cameroon`) → paramètres `language`/region SearXNG.
- Retourne `[{title, url, snippet, score}]` (score = score SearXNG, sinon dérivé du rang).
- **Dépend de :** `httpx.AsyncClient`, `SEARXNG_URL`.

### 5.2 `scraper.py`
- `async fetch_and_extract(url) -> str` : fetch HTML puis extraction du contenu principal.
- Fetch : `httpx` avec timeout (`SCRAPE_FETCH_TIMEOUT_MS`, défaut 15000), en-têtes
  navigateur, TLS tolérant configurable (`SCRAPE_ALLOW_INSECURE_TLS`, défaut `true` — de
  nombreux sites .gouv/.edu ont des certificats mal configurés ; lecture publique en
  seule-lecture, donc risque acceptable, miroir du comportement Traillearn existant).
- Gardes (miroir de `ai-discovery-html-fetch.ts`) : Content-Type HTML/XHTML uniquement,
  Content-Length ≤ 2 Mo, troncature finale à `SCRAPE_MAX_CHARS` (défaut 20000).
- Extraction : `trafilatura.extract(html)` → repli `readability-lxml` → repli nettoyage
  regex. Si le résultat est trop court (< 200 car.), on conserve le meilleur disponible.
- **Dépend de :** `httpx`, `trafilatura`, `readability-lxml`, `lxml`.

### 5.3 `search_handler.py`
- `async handle_search(req) -> SearchResponse` : orchestration.
- SearXNG → pour chaque hit, scrape en parallèle borné par `asyncio.Semaphore`
  (`SCRAPE_CONCURRENCY`, défaut 5) avec timeout par page.
- `content` = texte scrapé ; si le scrape échoue/timeout → repli sur le snippet SearXNG
  (jamais de `content` vide pour une URL valide).
- Tri/limitation à `max_results`.
- **Dépend de :** `searxng_client`, `scraper`.

### 5.4 `server.py`
- App FastAPI : `POST /search`, `GET /health`.
- Validation des entrées/sorties via modèles Pydantic.
- Auth Bearer optionnelle (cf. §4).
- **Dépend de :** `fastapi`, `uvicorn`, `search_handler`.

### 5.5 `config.py`
- Lecture centralisée des variables d'env (cf. §7) avec valeurs par défaut.

## 6. Changements côté Traillearn (minimes)

1. `apps/backend/src/services/tavily/tavily-client.ts` : remplacer la constante codée en
   dur
   ```ts
   const TAVILY_URL = "https://api.tavily.com/search";
   ```
   par
   ```ts
   const TAVILY_URL = process.env["TAVILY_URL"] ?? "https://api.tavily.com/search";
   ```
   (+ test couvrant l'override par env).
2. Configuration serveur (`/etc/traillearn/app.env`) :
   ```
   TAVILY_URL=http://127.0.0.1:8088/search
   TAVILY_API_KEY=local-dummy   # le client refuse d'appeler sans clé ; valeur factice suffit
   ```
3. **Aucune autre modification** : cache Redis, retry, round-robin et métriques continuent
   d'envelopper le service local.

## 7. Variables d'environnement (service)

| Variable | Défaut | Rôle |
|---|---|---|
| `SEARXNG_URL` | `http://searxng:8080` | URL interne SearXNG (réseau Docker) |
| `SERVICE_PORT` | `8088` | Port d'écoute du service |
| `LOCAL_SEARCH_TOKEN` | _(vide)_ | Si défini, exige ce Bearer ; sinon auth ignorée |
| `SCRAPE_CONCURRENCY` | `5` | Pages scrapées en parallèle par requête |
| `SCRAPE_FETCH_TIMEOUT_MS` | `15000` | Timeout fetch par page |
| `SCRAPE_MAX_CHARS` | `20000` | Troncature du contenu extrait |
| `SCRAPE_ALLOW_INSECURE_TLS` | `true` | Tolérance certificats invalides au scraping |

## 8. Déploiement

`TraillearnTavily/docker-compose.yml` :
- `searxng` : image `searxng/searxng`, config `format: json` activée, port interne 8080
  (non exposé à l'extérieur), volume de config.
- `traillearn-search` : build du `Dockerfile` Python local, port `127.0.0.1:8088:8088`,
  `depends_on: searxng`, healthcheck sur `/health`.

Aucun port exposé publiquement : seul le backend Traillearn (même VM) appelle
`http://127.0.0.1:8088/search`.

## 9. Gestion d'erreurs & résilience

- SearXNG injoignable → `results: []` → client Traillearn = `unavailable` (déjà géré).
- Scrape d'une page échoue/timeout → repli snippet, les autres URLs continuent.
- Concurrence bornée + timeout par page → pas de requête qui traîne indéfiniment.
- Cache : assuré **en amont** par le Redis de Traillearn (7 j par couple query+opts). Le
  service reste **stateless** en V1. (Cache interne de pages = amélioration future, YAGNI.)

## 10. Tests (TDD, `pytest`)

- `searxng_client` : mock httpx → parsing correct, mapping pays.
- `scraper` : fixtures HTML → texte attendu, garde Content-Type (rejet PDF), repli regex.
- `search_handler` : SearXNG + scraper mockés → format Tavily exact, repli snippet sur
  échec de scrape, respect de `max_results`, concurrence.
- `server` : test d'intégration FastAPI (`TestClient`) sur `/search` et `/health`, auth.
- Côté Traillearn : test unitaire de l'override `TAVILY_URL` par env.

## 11. Hors périmètre (V1 — YAGNI)

- Cache de pages interne au service (le Redis Traillearn couvre les requêtes identiques).
- Repli automatique vers l'API Tavily (l'utilisateur a choisi 100 % auto-hébergé).
- Rendu JavaScript headless (Playwright) — ajout possible plus tard si des sites SPA
  reviennent vides, comme le flag `USE_PLAYWRIGHT_FALLBACK` existant côté Traillearn.
- Métriques/observabilité avancées au-delà de `/health`.

## 12. Critères de réussite

1. `POST /search` renvoie un JSON au format Tavily exact, validé par les tests.
2. Le backend Traillearn fonctionne sans modification de code consommateur, uniquement
   via `TAVILY_URL` + clé factice.
3. Qualité d'enrichissement comparable à Tavily (contenu principal extrait, pas de bruit
   nav/pubs).
4. Coût par requête ≈ 0 €.
