# Déploiement Vercel

## Instance déployée

- Projet : `asonkeng/traillearn-search`.
- URL de production : https://traillearn-search.vercel.app
- Endpoint client : `POST https://traillearn-search.vercel.app/search`.
- Authentification : `Authorization: Bearer <LOCAL_SEARCH_TOKEN>` ; le token
  existant de la VM a été conservé dans les environnements production et preview.
- Variables et secrets configurés directement dans Vercel, sans fichier secret
  dans GitHub. `SEARXNG_URL` provient de la liaison privée.
- Déploiement effectué par le CLI. Le déploiement automatique depuis GitHub
  reste à connecter : Vercel demande une connexion GitHub sur le compte utilisateur.

Validation du 23 septembre 2026 : `/health` répond 200 ; `/search` sans token
répond 401 ; une recherche Python renvoie deux pages avec 1 393 et 688 caractères
de contenu. Deux recherches simultanées (admission au Cameroun et bourses en
France) renvoient chacune trois résultats. `/searxng/healthz` répond 404 sur le
domaine public. Les 32 tests Python ont également réussi localement.

La bascule du client Traillearn et le retrait de la VM restent à effectuer.

Le fichier `vercel.json` définit une API FastAPI publique et un conteneur
SearXNG privé. La liaison de service injecte `SEARXNG_URL` dans l'API : ne pas
définir cette variable manuellement avec l'adresse Docker de la VM.

## Stockage et secrets

Aucune base de données ni stockage de fichiers externe n'est nécessaire.
La configuration non secrète est dans `searxng/settings.yml` de ce dossier.
SearXNG lit `SEARXNG_SECRET` au démarrage ; le conteneur refuse de démarrer
si cette variable manque. Les éventuels caches locaux sont jetables.
Le limiteur SearXNG est désactivé et le service n'a aucune route publique.

Variables à configurer pour chaque environnement Vercel utilisé :

| Variable | Valeur |
| --- | --- |
| `SEARXNG_SECRET` | Secret aléatoire stable, au moins 32 octets |
| `LOCAL_SEARCH_TOKEN` | Secret Bearer de l'API ; conserver celui du client lors de la migration |
| `SCRAPE_CONCURRENCY` | `5` |
| `SCRAPE_FETCH_TIMEOUT_MS` | `15000` |
| `SCRAPE_MAX_CHARS` | `20000` |
| `SCRAPE_ALLOW_INSECURE_TLS` | `false` |
| `SEARXNG_ENGINES` | Facultatif ; moteurs à valider depuis Vercel |
| `SEARCH_COUNTRY_LANGUAGE` | Facultatif ; reprendre la configuration existante |
| `SEARCH_BLOCKLIST_DOMAINS` | Facultatif ; omettre pour garder les exclusions par défaut |

`BIND_HOST` et `SERVICE_PORT` concernent le déploiement Docker existant.
Le conteneur SearXNG utilise `PORT` si défini, sinon le port Vercel par défaut : 80.
Les fichiers `.env`, les sauvegardes et la configuration secrète de la VM sont
exclus de l'envoi Vercel. Ne jamais les copier dans l'image.

## Validation avant migration

1. S'authentifier avec `vercel login`, puis lier le projet avec `vercel link`.
2. Configurer les variables et déployer une preview avec `vercel deploy`.
3. Vérifier `/health`, le rejet des recherches non authentifiées et des recherches
   authentifiées avec des résultats non vides et du contenu extrait.
4. Vérifier que SearXNG n'a pas de route publique, et répéter les recherches
   après une période d'inactivité pour tester le démarrage à froid.
5. Déployer en production, basculer le client Traillearn, puis valider de nouveau.
6. Arrêter la VM uniquement après validation ; conserver un retour arrière avant
   suppression définitive des ressources.

Une réponse `/health` positive ne valide pas la recherche. Certains moteurs
peuvent refuser les adresses IP d'hébergeurs ; une réponse HTTP 200 avec une liste
vide ne suffit donc pas à déclarer la migration réussie.

Vercel Services et Container Images sont en bêta. Le fonctionnement cloud et
les limites du compte doivent être vérifiés avant de retirer la VM.

Références :
- https://vercel.com/docs/services
- https://vercel.com/docs/services/bindings
- https://vercel.com/docs/functions/container-images
