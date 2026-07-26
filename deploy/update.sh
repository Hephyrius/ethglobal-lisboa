#!/usr/bin/env bash
# Update the running stack. Lives at /srv/scipio/update.sh on the droplet.
#
#     scripts/vps.py deploy      # from a dev machine
#     bash /srv/scipio/update.sh # or here
#
# Build the API image from the tree `vps.py sync` uploaded, restart, verify,
# reclaim disk.
#
# Only the API is built here. The dApp is on Vercel — `next build` peaks well
# above this box's 961 MiB, whereas a Python image with no compiler in it builds
# in a couple of minutes.

set -eu
cd "$(dirname "$0")"

log() { printf "\033[36m==>\033[0m %s\n" "$1"; }
ok()  { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad() { printf "  \033[31m✗\033[0m %s\n" "$1"; }

COMPOSE="docker compose -f docker-compose.yml"

[ -f .env ] || { bad ".env missing — run: scripts/vps.py push-env"; exit 1; }

# ── what is running now ───────────────────────────────────────────────────
log "current"
$COMPOSE ps --format '  {{.Service}}  {{.Image}}  {{.Status}}' 2>/dev/null || echo "  (nothing running)"

log "build"
# The 4 GB swapfile exists partly for this: uv resolving and installing web3
# and its dependencies transiently needs more than the box has resident.
$COMPOSE build api

log "restart"
# --remove-orphans so a service deleted from the compose file actually stops,
# rather than lingering as a container nothing manages and nothing updates.
$COMPOSE up -d --remove-orphans

# ── verify, rather than assume ────────────────────────────────────────────
# `up -d` returns as soon as containers are CREATED. A container that starts and
# immediately crashes satisfies it. So does one whose image is fine and whose
# config is wrong.
#
# Probed from INSIDE the container, not from the host. The API is `expose:`d, not
# published — it is reachable only through Caddy and the compose network, which
# is the point. An earlier version of this script curled localhost:8000 from the
# host, got connection-refused against a perfectly healthy API, and reported the
# deploy as failed.
#
# Python rather than curl because `python:3.12-slim` has neither curl nor wget,
# and installing one to run a health check would add an apt layer to every build.
log "waiting for health"
PROBE='import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=4))["mode"])'
deadline=$(( $(date +%s) + 120 ))
mode=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  # `mode` specifically, not just a 200. A fixture-mode API answers every request
  # and validates every response over invented data, so "it responded" is not
  # evidence that anything behind it is real.
  mode="$($COMPOSE exec -T api python -c "$PROBE" 2>/dev/null | tr -d '[:space:]')"
  [ -n "$mode" ] && break
  sleep 3
done
case "$mode" in
  live)    ok "api live on all three seams" ;;
  fixture)
    bad "api is serving FIXTURES — every request will succeed over invented data"
    bad "check AGENT_MODE, AGENT_DATA_REGISTRY, AGENT_VENUE_REGISTRY in .env"
    exit 1 ;;
  *)
    bad "api did not become healthy within 120s"
    $COMPOSE logs --tail=40 api
    exit 1 ;;
esac

# The dApp is on Vercel and is not checked from here — this box knows nothing
# about whether it deployed. What IS worth checking is the seam between them,
# because it is the one that fails silently: a rejected CORS origin returns 400
# on the preflight, the dApp falls back to reading the chain, and it reports
# "the agent API is unreachable". That reads as a dead backend while every check
# above is green.
ORIGIN="${CORS_PROBE_ORIGIN:-https://scipio.capital}"
CORS="import urllib.request as u
r = u.Request('http://127.0.0.1:8000/health', method='OPTIONS')
r.add_header('Origin', '$ORIGIN')
r.add_header('Access-Control-Request-Method', 'GET')
try:
    print(u.urlopen(r, timeout=6).status)
except Exception as e:
    print(getattr(e, 'code', 0))"
code="$($COMPOSE exec -T api python -c "$CORS" 2>/dev/null | tr -d '[:space:]')"
if [ "$code" = "200" ]; then
  ok "CORS preflight from $ORIGIN accepted"
else
  bad "CORS preflight from $ORIGIN returned $code — the dApp will report the API unreachable"
  bad "fix AGENT_CORS_ORIGINS in .env, then push-env and re-run"
  exit 1
fi

# ── reclaim ───────────────────────────────────────────────────────────────
# 24 GB disk, and every rebuild leaves the previous image dangling. Images and
# the build cache only — NOT `system prune --volumes`, which would delete
# agent-state and with it every open Aqua position.
log "reclaim"
docker image prune -f >/dev/null
# Layer cache from superseded builds. Keeps recent layers so the next build is
# still incremental, drops anything older than a day.
docker builder prune -f --filter until=24h >/dev/null 2>&1 || true
ok "dangling images and stale build cache removed"
df -h / | tail -1 | sed 's/^/  /'
free -h | sed -n '2p;3p' | sed 's/^/  /'

echo
$COMPOSE ps --format '  {{.Service}}  {{.Status}}'
