# Prompt d'intégration — à transmettre à l'agent de dev Traillearn

Copiez-collez le bloc ci-dessous à l'agent chargé du développement Traillearn.

---

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
>    (selon votre workflow : merge ou rebase + PR). C'est un changement isolé et
>    rétrocompatible.
> 2. Lance les tests du backend et le typecheck :
>    - `cd apps/backend && npx tsx --test src/services/tavily/tavily-client.test.ts`
>      (le nouveau test + les pré-existants doivent passer)
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
>    puis `pm2 reload ecosystem.config.cjs`. `TAVILY_API_KEY` doit être non vide
>    (le client refuse d'appeler sans clé) ; valeur factice si l'auth du service
>    est désactivée, sinon mettre la valeur de `LOCAL_SEARCH_TOKEN`.
>
> **Important :** ne modifie pas le fichier généré `apps/frontend/next-env.d.ts`
> (présent en working tree de la branche d'origine, sans rapport avec ce travail).
> Ne touche pas au cache/retry/round-robin/métriques du `TavilyClient` : ils sont
> volontairement conservés et enveloppent le service local.

---
