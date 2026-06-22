"""Page HTML de test (servie sur `GET /`).

Servie par le service lui-même → même origine que `POST /search`, donc aucun
problème CORS. Aucune dépendance externe (CSS/JS inline). Utile pour vérifier
manuellement que SearXNG + scraping renvoient des résultats exploitables.
"""

from __future__ import annotations

# La chaîne contient des accolades JS → on évite f-string/.format pour ne pas
# avoir à les échapper. Page volontairement autonome (aucun asset externe).
TEST_PAGE_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Traillearn Search — banc de test</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         max-width: 880px; margin: 0 auto; padding: 24px; line-height: 1.5; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  p.sub { margin: 0 0 20px; opacity: .7; font-size: .9rem; }
  form { display: grid; gap: 12px; grid-template-columns: 1fr 1fr;
         background: rgba(127,127,127,.08); padding: 16px; border-radius: 12px; }
  .full { grid-column: 1 / -1; }
  label { display: block; font-size: .8rem; font-weight: 600; margin-bottom: 4px; }
  input, select { width: 100%; padding: 8px 10px; border-radius: 8px;
                  border: 1px solid rgba(127,127,127,.4); background: transparent;
                  color: inherit; font-size: .95rem; }
  button { padding: 10px 16px; border: 0; border-radius: 8px; cursor: pointer;
           background: #2563eb; color: #fff; font-weight: 600; font-size: .95rem; }
  button:disabled { opacity: .5; cursor: progress; }
  #status { margin: 16px 0 8px; font-size: .9rem; min-height: 1.2em; }
  .card { border: 1px solid rgba(127,127,127,.25); border-radius: 10px;
          padding: 14px; margin: 10px 0; }
  .card a { font-weight: 600; font-size: 1.02rem; text-decoration: none; color: #2563eb; }
  .card .url { font-size: .78rem; opacity: .6; word-break: break-all; margin: 2px 0 8px; }
  .card .score { float: right; font-size: .75rem; opacity: .7; }
  .card .content { font-size: .88rem; white-space: pre-wrap; max-height: 9em; overflow: auto; }
  details { margin-top: 18px; } pre { overflow: auto; font-size: .8rem;
          background: rgba(127,127,127,.1); padding: 10px; border-radius: 8px; }
</style>
</head>
<body>
  <h1>Traillearn Search — banc de test</h1>
  <p class="sub">Interroge <code>POST /search</code> de ce service (SearXNG + scraping). Format compatible Tavily.</p>

  <form id="f">
    <div class="full">
      <label for="q">Requête</label>
      <input id="q" name="q" placeholder="bourses études France" required>
    </div>
    <div>
      <label for="max">Nombre de résultats</label>
      <input id="max" name="max" type="number" min="1" max="50" value="5">
    </div>
    <div>
      <label for="depth">Profondeur</label>
      <select id="depth" name="depth">
        <option value="basic">basic</option>
        <option value="advanced">advanced</option>
      </select>
    </div>
    <div>
      <label for="country">Pays (anglais minuscule, optionnel)</label>
      <input id="country" name="country" placeholder="france">
    </div>
    <div>
      <label for="token">Bearer token (si LOCAL_SEARCH_TOKEN défini)</label>
      <input id="token" name="token" placeholder="(vide si non configuré)">
    </div>
    <div class="full">
      <button id="go" type="submit">Rechercher</button>
    </div>
  </form>

  <div id="status"></div>
  <div id="results"></div>
  <details>
    <summary>Réponse JSON brute</summary>
    <pre id="raw">—</pre>
  </details>

<script>
const f = document.getElementById('f');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const rawEl = document.getElementById('raw');
const go = document.getElementById('go');

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ));
}

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  go.disabled = true;
  resultsEl.innerHTML = '';
  rawEl.textContent = '—';
  statusEl.textContent = 'Recherche en cours…';

  const body = {
    query: document.getElementById('q').value,
    max_results: Number(document.getElementById('max').value) || 5,
    search_depth: document.getElementById('depth').value,
  };
  const country = document.getElementById('country').value.trim();
  if (country) body.country = country;

  const headers = { 'Content-Type': 'application/json' };
  const token = document.getElementById('token').value.trim();
  if (token) headers['Authorization'] = 'Bearer ' + token;

  const t0 = performance.now();
  try {
    const resp = await fetch('/search', { method: 'POST', headers, body: JSON.stringify(body) });
    const ms = Math.round(performance.now() - t0);
    const data = await resp.json();
    rawEl.textContent = JSON.stringify(data, null, 2);
    const results = (data && data.results) || [];
    if (!resp.ok) {
      statusEl.textContent = 'HTTP ' + resp.status + ' — ' + (data.detail || 'erreur');
    } else if (results.length === 0) {
      statusEl.textContent = 'Aucun résultat (' + ms + ' ms). SearXNG indisponible ou requête sans correspondance.';
    } else {
      statusEl.textContent = results.length + ' résultat(s) en ' + ms + ' ms.';
      for (const r of results) {
        const card = document.createElement('div');
        card.className = 'card';
        const score = (typeof r.score === 'number') ? r.score.toFixed(2) : '';
        card.innerHTML =
          '<span class="score">score ' + esc(score) + '</span>' +
          '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.title || r.url) + '</a>' +
          '<div class="url">' + esc(r.url) + '</div>' +
          '<div class="content">' + esc((r.content || '').slice(0, 1200)) + '</div>';
        resultsEl.appendChild(card);
      }
    }
  } catch (err) {
    statusEl.textContent = 'Échec réseau : ' + err;
  } finally {
    go.disabled = false;
  }
});
</script>
</body>
</html>
"""
