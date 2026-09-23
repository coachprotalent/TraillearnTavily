#!/bin/sh
set -eu

# SearXNG reads SEARXNG_SECRET directly; never bake it into an image.
: "${SEARXNG_SECRET:?Set SEARXNG_SECRET in the Vercel environment}"
export GRANIAN_HOST=0.0.0.0
export GRANIAN_PORT="${PORT:-80}"
exec /usr/local/searxng/.venv/bin/granian searx.webapp:app
