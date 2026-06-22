# Déploiement — Traillearn Search (Tavily local)

Guide de mise en service du service de recherche local sur le serveur (VM Azure)
qui héberge déjà le backend Traillearn. Le service tourne en deux conteneurs
Docker (SearXNG + service FastAPI) et n'expose **aucun port public** : seul le
backend Traillearn (même VM) l'appelle sur `http://127.0.0.1:8088`.

---

## 1. Prérequis sur la VM

- Docker Engine + plugin Compose v2 (`docker compose version` doit répondre).
  Installation (Ubuntu/Debian) si absent :
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"   # puis se reconnecter
  ```
- ~1 Go de RAM libre et un accès Internet sortant (SearXNG interroge Google/Bing/DDG).

## 2. Récupérer le code sur la VM

Copier le dossier `TraillearnTavily/` sur la VM, par exemple dans `/opt/traillearn-search` :

```bash
# Option A — via git (si le dépôt est poussé sur un remote)
sudo git clone <URL_DU_DEPOT_TraillearnTavily> /opt/traillearn-search

# Option B — copie directe depuis le poste (depuis le poste Windows/WSL)
rsync -av --exclude .venv --exclude .git ./TraillearnTavily/ user@vm:/opt/traillearn-search/
```

## 3. Configurer la clé secrète SearXNG

SearXNG exige une `secret_key` aléatoire en production. Elle est injectée par
variable d'environnement (le fichier versionné ne contient qu'un placeholder) :

```bash
cd /opt/traillearn-search
echo "SEARXNG_SECRET_KEY=$(openssl rand -hex 32)" > .env
```

> Le `docker-compose.yml` lit `${SEARXNG_SECRET_KEY:-change-me-in-production}` ;
> le `.env` ci-dessus fournit la vraie valeur. `.env` est ignoré par git.

(Optionnel) Pour exiger un Bearer token sur `/search`, ajouter au même `.env` :
```bash
echo "LOCAL_SEARCH_TOKEN=$(openssl rand -hex 24)" >> .env
```
et décommenter la ligne `LOCAL_SEARCH_TOKEN=` du service dans `docker-compose.yml`
(la passer en `- LOCAL_SEARCH_TOKEN=${LOCAL_SEARCH_TOKEN}`).

## 4. Démarrer la stack

```bash
cd /opt/traillearn-search
docker compose up -d --build
```

Le service `traillearn-search` attend que SearXNG soit **sain**
(`condition: service_healthy`) avant de démarrer — pas de résultats vides au
démarrage à froid.

Suivre le démarrage :
```bash
docker compose ps          # les 2 services doivent être "running"/"healthy"
docker compose logs -f traillearn-search
```

## 5. Vérifier

```bash
# Santé
curl -s http://127.0.0.1:8088/health
# → {"status":"ok"}

# Recherche réelle (doit renvoyer des résultats avec title/url/content/score)
curl -s -X POST http://127.0.0.1:8088/search \
  -H "Content-Type: application/json" \
  -d '{"query":"bourses études France","max_results":3}' | head -c 800
```

**Page de test graphique** : `http://127.0.0.1:8088/`. La VM n'exposant pas ce
port publiquement, ouvrez-la via un tunnel SSH depuis votre poste :
```bash
ssh -L 8088:127.0.0.1:8088 user@vm
# puis dans le navigateur du poste : http://127.0.0.1:8088/
```

## 6. Brancher le backend Traillearn

Une fois le service vérifié, pointer Traillearn dessus. Éditer
`/etc/traillearn/app.env` :

```bash
TAVILY_URL=http://127.0.0.1:8088/search
TAVILY_API_KEY=local-dummy
```

> `TAVILY_API_KEY` doit être non vide (le client refuse d'appeler sans clé) ;
> la valeur factice suffit puisque l'auth est gérée côté service (ou désactivée).
> Si vous avez activé `LOCAL_SEARCH_TOKEN`, mettez plutôt cette valeur dans
> `TAVILY_API_KEY` (le client l'envoie en `Authorization: Bearer <clé>`).

Recharger les process :
```bash
pm2 reload ecosystem.config.cjs
```

> **Prérequis code** : la branche `feat/tavily-local-endpoint` (endpoint Tavily
> configurable via `TAVILY_URL`) doit être intégrée et déployée côté Traillearn.
> Voir le prompt d'intégration fourni séparément. Sans ce changement, le backend
> continue d'appeler `api.tavily.com` et ignore `TAVILY_URL`.

## 7. Mettre à jour le service

```bash
cd /opt/traillearn-search
git pull            # ou re-rsync
docker compose up -d --build
```

## 8. Exploitation

```bash
docker compose restart traillearn-search   # redémarrer le service seul
docker compose down                        # arrêter la stack
docker compose logs --tail=100 searxng     # logs SearXNG
```

- **Cache** : les requêtes identiques sont déjà mises en cache 7 j côté Redis de
  Traillearn → le service est sans état, on peut le redémarrer sans perte.
- **Rollback** : remettre `TAVILY_URL` et `TAVILY_API_KEY` aux valeurs Tavily
  d'origine dans `app.env` + `pm2 reload` ; le service local peut rester arrêté.

## 9. Limitations connues

- `SCRAPE_ALLOW_INSECURE_TLS=true` (défaut) désactive la vérification TLS lors du
  scraping des pages publiques — choix assumé (sites .gouv/.edu mal configurés),
  identique au comportement Traillearn existant. Passer à `false` pour un TLS strict.
- Pas de rendu JavaScript (pages SPA) en V1. Si certaines sources reviennent
  vides, envisager un repli navigateur headless (cf. `USE_PLAYWRIGHT_FALLBACK`
  côté Traillearn) dans une itération ultérieure.
- Si l'IP de la VM se fait limiter par les moteurs (volume élevé), envisager une
  VM/IP dédiée pour SearXNG.
