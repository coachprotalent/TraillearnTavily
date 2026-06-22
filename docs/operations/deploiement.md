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

SearXNG **refuse de démarrer** tant que sa `secret_key` vaut la valeur par défaut
`ultrasecretkey`. Comme on monte notre propre `settings.yml`, l'image ne la
remplace pas automatiquement — on écrit une vraie clé aléatoire dans le fichier :

```bash
cd /opt/traillearn-search
sed -i "s/ultrasecretkey/$(openssl rand -hex 32)/" searxng/settings.yml
```

> ⚠️ `git pull` (mise à jour) réinitialise `searxng/settings.yml` : relancer cette
> commande après chaque `git pull`. Vérifier : `grep secret_key searxng/settings.yml`.

(Optionnel) Pour exiger un Bearer token sur `/search` — le `docker-compose.yml` lit
déjà `LOCAL_SEARCH_TOKEN` depuis `.env`, rien d'autre à éditer :
```bash
echo "LOCAL_SEARCH_TOKEN=$(openssl rand -hex 24)" >> .env
```

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

**Page de test graphique** : `http://127.0.0.1:8088/`.

- **Accès sécurisé (recommandé)** — tunnel SSH depuis votre poste :
  ```bash
  ssh -L 8088:127.0.0.1:8088 user@vm
  # puis dans le navigateur du poste : http://127.0.0.1:8088/
  ```
- **Accès depuis un autre serveur/navigateur** — exposer le port :
  ```bash
  echo "BIND_HOST=0.0.0.0" >> .env
  echo "LOCAL_SEARCH_TOKEN=$(openssl rand -hex 24)" >> .env   # active l'auth
  docker compose up -d
  ```
  puis ouvrir le port 8088 dans le **NSG / pare-feu Azure** (de préférence
  restreint à l'IP du serveur de test), et ouvrir `http://<IP_PUBLIQUE_VM>:8088/`
  en saisissant le token dans le champ « Bearer token » de la page.
  ⚠️ N'exposez `0.0.0.0` que le temps des tests (risque SSRF, pas de TLS propre) ;
  repassez ensuite à `BIND_HOST=127.0.0.1`. Pour un accès durable, mettre un
  reverse proxy HTTPS devant le service.

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
- **SSRF (risque résiduel assumé)** : le service scrape les URLs renvoyées par
  SearXNG sans filtrage d'hôte/IP (avec suivi de redirections). Une source
  malveillante pourrait pointer vers une adresse interne (ex. endpoint de
  métadonnées cloud `169.254.169.254`). Acceptable car le service est interne et
  ce comportement reflète l'existant Traillearn ; pour durcir, bloquer les plages
  link-local/privées côté scraper dans une itération ultérieure.
