# Traillearn Search — Tavily local

Service de recherche web **auto-hébergé et compatible avec l'API Tavily**, conçu
pour remplacer l'API Tavily (facturée au crédit) dans le projet **Traillearn**, à
coût quasi nul.

Il s'appuie sur **SearXNG** (méta-moteur agrégeant Google/Bing/DuckDuckGo) pour
trouver les URLs, puis **scrape** chaque page (`trafilatura` → `readability` →
nettoyage regex) pour produire un contenu propre exploitable par un LLM. Le format
de réponse est strictement identique à Tavily, donc le backend Traillearn fonctionne
sans changement de code — uniquement une variable d'environnement à pointer.

```
Traillearn (TavilyClient : cache Redis 7j + retry + métriques — inchangé)
   │  POST /search  {query, max_results, search_depth, country}
   ▼
TraillearnTavily  (service FastAPI, port 8088)
   ├─ 1. SearXNG  GET /search?format=json        → [{title, url, snippet, score}]
   ├─ 2. scrape parallèle borné de chaque URL    → contenu principal propre
   └─ 3. réponse {results:[{title,url,content,score}]}  ← format Tavily exact
   ▼
SearXNG (Docker, interne) → Google / Bing / DuckDuckGo
```

---

## Sommaire

- [Démarrage rapide](#démarrage-rapide)
- [Contrat HTTP](#contrat-http)
- [Procédure de déploiement (VM)](#procédure-de-déploiement-vm)
- [Variables d'environnement](#variables-denvironnement)
- [Brancher le backend Traillearn](#brancher-le-backend-traillearn)
- [Prompt d'intégration pour l'agent de dev Traillearn](#prompt-dintégration-pour-lagent-de-dev-traillearn)
- [Page de test graphique](#page-de-test-graphique)
- [Accès distant durable (reverse proxy HTTPS)](#accès-distant-durable-reverse-proxy-https)
- [Développement local](#développement-local)
- [Limitations connues](#limitations-connues)

---

## Démarrage rapide

```bash
git clone https://github.com/coachprotalent/TraillearnTavily.git
cd TraillearnTavily
echo "SEARXNG_SECRET_KEY=$(openssl rand -hex 32)" > .env
docker compose up -d --build
curl -s http://127.0.0.1:8088/health        # → {"status":"ok"}
```

**Ouvrir l'interface graphique de test :**

| Besoin | Comment |
|---|---|
| Depuis la VM uniquement (sécurisé) | Tunnel SSH : `ssh -L 8088:127.0.0.1:8088 user@vm`, puis `http://127.0.0.1:8088/` |
| Depuis un autre serveur/navigateur | `echo "BIND_HOST=0.0.0.0" >> .env` + activer un token, `docker compose up -d`, ouvrir le port 8088 (NSG Azure), puis `http://<IP_VM>:8088/` — voir [Page de test](#page-de-test-graphique) |
| Accès durable + HTTPS | Reverse proxy → voir [Accès distant durable](#accès-distant-durable-reverse-proxy-https) |

---

## Contrat HTTP

| Endpoint | Description |
|---|---|
| `POST /search` | Recherche. Corps `{query, max_results, search_depth, country?}`. Header `Authorization: Bearer <token>` (validé seulement si `LOCAL_SEARCH_TOKEN` défini). Réponse `{results:[{title,url,content,score}]}`. Toujours `200` (erreur interne → `200` avec `results: []`). |
| `GET /health` | Sonde de vivacité → `{"status":"ok"}`. |
| `GET /` | Page de test graphique (banc d'essai). |

Exemple :
```bash
curl -s -X POST http://127.0.0.1:8088/search \
  -H "Content-Type: application/json" \
  -d '{"query":"bourses études France","max_results":3}'
```

---

## Procédure de déploiement (VM)

Le service tourne en **deux conteneurs Docker** (SearXNG + service FastAPI) sur la
même VM que le backend Traillearn. **Aucun port public** : seul le backend (même VM)
l'appelle sur `http://127.0.0.1:8088`.

### 1. Prérequis

Docker Engine + plugin Compose v2 (`docker compose version` doit répondre) :
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # puis se reconnecter
```

### 2. Récupérer le code

```bash
sudo git clone https://github.com/coachprotalent/TraillearnTavily.git /opt/traillearn-search
cd /opt/traillearn-search
```

### 3. Configurer les secrets

SearXNG exige une clé secrète aléatoire (injectée par env, pas dans le fichier versionné) :
```bash
echo "SEARXNG_SECRET_KEY=$(openssl rand -hex 32)" > .env
```

(Optionnel) Pour exiger un Bearer token sur `/search` — le `docker-compose.yml`
lit déjà cette valeur depuis `.env`, rien d'autre à éditer :
```bash
echo "LOCAL_SEARCH_TOKEN=$(openssl rand -hex 24)" >> .env
```

### 4. Démarrer

```bash
docker compose up -d --build
docker compose ps                       # les 2 services : running / healthy
docker compose logs -f traillearn-search
```
Le service attend que SearXNG soit **sain** (`condition: service_healthy`) avant de
démarrer — pas de résultats vides au démarrage à froid.

### 5. Vérifier

```bash
curl -s http://127.0.0.1:8088/health
# → {"status":"ok"}

curl -s -X POST http://127.0.0.1:8088/search \
  -H "Content-Type: application/json" \
  -d '{"query":"bourses études France","max_results":3}' | head -c 800
```

### 6. Mettre à jour

```bash
cd /opt/traillearn-search && git pull && docker compose up -d --build
```

### Exploitation

```bash
docker compose restart traillearn-search   # redémarrer le service seul
docker compose down                        # arrêter la stack
docker compose logs --tail=100 searxng     # logs SearXNG
```

---

## Variables d'environnement

### Service TraillearnTavily

Définies dans `docker-compose.yml` (et/ou `.env`). Toutes ont une valeur par défaut.

| Variable | Défaut | Rôle |
|---|---|---|
| `SEARXNG_SECRET_KEY` | `change-me-in-production` | **À définir en prod** (`.env`). Clé secrète SearXNG, injectée dans `settings.yml` au démarrage. |
| `SEARXNG_URL` | `http://searxng:8080` | URL interne de SearXNG (réseau Docker). |
| `SERVICE_PORT` | `8088` | Port d'écoute du service. |
| `BIND_HOST` | `127.0.0.1` | Interface du mapping de port hôte. `127.0.0.1` = accessible seulement depuis la VM ; `0.0.0.0` = exposé à d'autres machines (tests navigateur distant). |
| `LOCAL_SEARCH_TOKEN` | _(vide)_ | Si défini, exige `Authorization: Bearer <token>` sur `/search` ; sinon auth ignorée. **Recommandé si `BIND_HOST=0.0.0.0`.** |
| `SCRAPE_CONCURRENCY` | `5` | Pages scrapées en parallèle par requête. |
| `SCRAPE_FETCH_TIMEOUT_MS` | `15000` | Timeout de fetch par page (ms). |
| `SCRAPE_MAX_CHARS` | `20000` | Troncature du contenu extrait (caractères). |
| `SCRAPE_ALLOW_INSECURE_TLS` | `true` | Tolérance aux certificats TLS invalides lors du scraping. |

### Projet Traillearn (pour basculer vers le service local)

À configurer dans `/etc/traillearn/app.env` sur la VM :

| Variable | Valeur | Rôle |
|---|---|---|
| `TAVILY_URL` | `http://127.0.0.1:8088/search` | Pointe le `TavilyClient` vers le service local au lieu de `api.tavily.com`. |
| `TAVILY_API_KEY` | `local-dummy` | Doit être non vide (le client refuse d'appeler sans clé). Si `LOCAL_SEARCH_TOKEN` est activé côté service, mettre cette valeur ici. |

> Prérequis : la branche `feat/tavily-local-endpoint` (endpoint configurable via
> `TAVILY_URL`) doit être intégrée et déployée côté Traillearn — cf. le prompt
> d'intégration ci-dessous. Sans ce changement, le backend ignore `TAVILY_URL`.

---

## Brancher le backend Traillearn

```bash
# /etc/traillearn/app.env
TAVILY_URL=http://127.0.0.1:8088/search
TAVILY_API_KEY=local-dummy
```
puis :
```bash
pm2 reload ecosystem.config.cjs
```

**Rollback** : remettre les valeurs Tavily d'origine dans `app.env` + `pm2 reload` ;
le service local peut rester arrêté.

---

## Prompt d'intégration pour l'agent de dev Traillearn

Copiez-collez le bloc ci-dessous à l'agent chargé du développement Traillearn pour
intégrer le changement dans la branche principale.

> **Contexte.** Une branche `feat/tavily-local-endpoint` existe dans le dépôt
> Traillearn (créée depuis `feat/school-scoring-epic006`). Elle contient **un seul
> commit** (`165a967`) qui rend l'endpoint de recherche Tavily configurable, afin
> que le backend puisse cibler un service « Tavily local » auto-hébergé
> (SearXNG + scraping) au lieu de l'API payante `api.tavily.com`.
>
> **Le changement (2 fichiers uniquement) :**
> - `apps/backend/src/services/tavily/tavily-client.ts` :
>   - la constante `TAVILY_URL = "https://api.tavily.com/search"` est renommée
>     `TAVILY_DEFAULT_URL` ;
>   - `TavilyClientDeps` reçoit un champ optionnel `baseUrl?: string` ;
>   - le client résout l'URL ainsi :
>     `deps?.baseUrl ?? process.env["TAVILY_URL"] ?? TAVILY_DEFAULT_URL` ;
>   - l'appel `fetch` utilise `this.baseUrl`.
>   - **Rétrocompatible** : sans `baseUrl` ni `TAVILY_URL`, le comportement est
>     identique (appel de l'API Tavily publique). Aucun changement requis chez les
>     ~4 consommateurs (`new TavilyClient({ usage })`).
> - `apps/backend/src/services/tavily/tavily-client.test.ts` : un test qui prouve
>   qu'un `baseUrl` injecté est bien l'URL effectivement appelée.
>
> **Ta mission :**
> 1. Intègre `feat/tavily-local-endpoint` dans la branche principale du projet
>    (merge ou rebase + PR). C'est un changement isolé et rétrocompatible.
> 2. Lance les tests du backend et le typecheck :
>    - `cd apps/backend && npx tsx --test src/services/tavily/tavily-client.test.ts`
>    - suite complète : `npm run test -w @traillearn/backend`
>    - `npm run typecheck -w @traillearn/backend`
> 3. Vérifie qu'aucune référence à l'ancienne constante `TAVILY_URL` ne subsiste
>    (seuls le commentaire et `process.env["TAVILY_URL"]` doivent rester).
> 4. (Déploiement, séparé) Pour activer le service local en production, ajouter à
>    `/etc/traillearn/app.env` :
>    ```
>    TAVILY_URL=http://127.0.0.1:8088/search
>    TAVILY_API_KEY=local-dummy
>    ```
>    puis `pm2 reload ecosystem.config.cjs`. `TAVILY_API_KEY` doit être non vide ;
>    valeur factice si l'auth du service est désactivée, sinon mettre la valeur de
>    `LOCAL_SEARCH_TOKEN`.
>
> **Important :** ne modifie pas le fichier généré `apps/frontend/next-env.d.ts`.
> Ne touche pas au cache/retry/round-robin/métriques du `TavilyClient` : ils sont
> volontairement conservés et enveloppent le service local.

---

## Page de test graphique

Une page web autonome est servie sur `GET /` (même origine que `/search`, donc pas
de CORS). Elle permet de lancer des requêtes et de visualiser les résultats.

### Option A — sans exposer le port (sécurisé, recommandé)

Tunnel SSH depuis votre poste :
```bash
ssh -L 8088:127.0.0.1:8088 user@vm
# puis dans le navigateur : http://127.0.0.1:8088/
```

### Option B — exposer le service à d'autres machines (tests navigateur distant)

Pour ouvrir l'interface depuis un autre serveur/navigateur, exposer le port :

1. **Activer l'auth** et **exposer** dans `.env` :
   ```bash
   echo "BIND_HOST=0.0.0.0" >> .env
   echo "LOCAL_SEARCH_TOKEN=$(openssl rand -hex 24)" >> .env
   ```
2. Redémarrer : `docker compose up -d`
3. **Ouvrir le port 8088 dans le NSG / pare-feu Azure**, idéalement restreint à
   l'IP du serveur de test :
   ```bash
   az network nsg rule create \
     --resource-group <RG> --nsg-name <NSG> \
     --name allow-traillearn-search --priority 320 \
     --access Allow --protocol Tcp --direction Inbound \
     --destination-port-ranges 8088 \
     --source-address-prefixes <IP_DU_SERVEUR_DE_TEST>/32
   ```
4. Dans le navigateur : `http://<IP_PUBLIQUE_VM>:8088/` — saisir le token dans le
   champ **Bearer token** de la page.

> ⚠️ **Sécurité.** Le service scrape des URLs arbitraires (risque SSRF) et n'a pas
> de chiffrement TLS en propre. N'exposez `0.0.0.0` que le temps des tests, gardez
> `LOCAL_SEARCH_TOKEN` activé, restreignez le NSG à l'IP du testeur, et repassez à
> `BIND_HOST=127.0.0.1` ensuite. Pour un accès durable, placez plutôt un reverse
> proxy HTTPS (Caddy/Nginx) devant le service.

---

## Accès distant durable (reverse proxy HTTPS)

Pour un accès distant **permanent et chiffré** (plutôt qu'un `BIND_HOST=0.0.0.0`
temporaire), placez un reverse proxy TLS devant le service. Gardez le service lié à
`127.0.0.1` (le défaut) : seul le proxy y accède, sur la même machine.

Prérequis : un nom de domaine pointant vers la VM (enregistrement DNS A) et les
ports **80/443** ouverts dans le NSG Azure. Des configs prêtes à l'emploi sont
fournies dans [`deploy/`](deploy/).

### Caddy (le plus simple — HTTPS/Let's Encrypt automatique)

`deploy/Caddyfile` :
```caddy
search.exemple.org {
    # TLS automatique (Let's Encrypt). Remplacez par votre domaine.
    reverse_proxy 127.0.0.1:8088
}
```
Lancement :
```bash
# Le service écoute déjà sur 127.0.0.1:8088 (BIND_HOST par défaut).
docker run -d --name caddy --network host \
  -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile" \
  -v caddy_data:/data -v caddy_config:/config \
  caddy:2
```
→ `https://search.exemple.org/` est servi avec un certificat valide, sans config TLS
manuelle. Pensez à activer `LOCAL_SEARCH_TOKEN` (le proxy ne fait pas l'auth).

### Nginx (si vous gérez déjà Nginx + certbot)

`deploy/nginx.conf.example` :
```nginx
server {
    listen 443 ssl;
    server_name search.exemple.org;

    ssl_certificate     /etc/letsencrypt/live/search.exemple.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/search.exemple.org/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8088;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;   # le scraping peut prendre quelques secondes
    }
}
server {                       # redirige HTTP → HTTPS
    listen 80;
    server_name search.exemple.org;
    return 301 https://$host$request_uri;
}
```
Certificat : `sudo certbot --nginx -d search.exemple.org`, puis `sudo nginx -s reload`.

> Avec un reverse proxy, **gardez `BIND_HOST=127.0.0.1`** et n'ouvrez que 80/443 au
> public. Activez `LOCAL_SEARCH_TOKEN` : le proxy chiffre le transport mais
> n'authentifie pas les appels.

---

## Développement local

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# (ou : .venv/bin/pip install -r requirements.txt sous Linux/macOS)
.venv/Scripts/python -m pip install pytest pytest-asyncio

# Tests
.venv/Scripts/python -m pytest -q

# Lancer le service (nécessite un SearXNG accessible via SEARXNG_URL)
.venv/Scripts/python -m app.server
```

Structure :
```
app/
  config.py          # configuration par variables d'env
  searxng_client.py  # interrogation SearXNG (JSON)
  scraper.py         # fetch + extraction du contenu principal
  search_handler.py  # orchestration (scrape parallèle borné)
  server.py          # API FastAPI (/search, /health, /)
  test_page.py       # page de test HTML
tests/               # suite pytest (21 tests)
deploy/              # configs reverse proxy HTTPS (Caddy, Nginx)
docs/                # spec, plan, guides d'exploitation
```

---

## Limitations connues

- `SCRAPE_ALLOW_INSECURE_TLS=true` (défaut) désactive la vérification TLS au
  scraping — choix assumé (sites .gouv/.edu mal configurés), identique à l'existant
  Traillearn. Passer à `false` pour un TLS strict.
- **SSRF (risque résiduel assumé)** : le service scrape les URLs renvoyées par
  SearXNG sans filtrage d'hôte/IP. Acceptable car interne ; pour durcir, bloquer les
  plages link-local/privées côté scraper dans une itération ultérieure.
- Pas de rendu JavaScript (pages SPA) en V1.
- Le cache des requêtes identiques est assuré en amont par le Redis de Traillearn
  (7 j) → le service est sans état et peut être redémarré sans perte.
