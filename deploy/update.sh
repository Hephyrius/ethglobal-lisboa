#!/usr/bin/env bash
# Update the running stack. Lives at /srv/scipio/update.sh on the droplet.
#
#     scripts/vps.py deploy      # from a dev machine
#     bash /srv/scipio/update.sh # or here
#
# Pull the newest images, restart, verify, reclaim disk. No build step: images
# are produced by .github/workflows/deploy-images.yml and this box has 1 vCPU.

set -eu
cd "$(dirname "$0")"

log() { printf "\033[36m==>\033[0m %s\n" "$1"; }
ok()  { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad() { printf "  \033[31m✗\033[0m %s\n" "$1"; }

COMPOSE="docker compose -f docker-compose.prod.yml"

[ -f .env ] || { bad ".env missing — run: scripts/vps.py push-env"; exit 1; }

# ── what is running now, so a rollback is possible ────────────────────────
# Recorded BEFORE the pull. Once `latest` moves, the digest that was working is
# not otherwise recoverable from the box, and "roll back to the one from twenty
# minutes ago" becomes guesswork against the registry's tag history.
log "current"
$COMPOSE images --quiet 2>/dev/null | sort -u > .previous-images || true
$COMPOSE ps --format '  {{.Service}}  {{.Image}}  {{.Status}}' 2>/dev/null || echo "  (nothing running)"

log "pull"
$COMPOSE pull

log "restart"
# --remove-orphans so a service deleted from the compose file actually stops,
# rather than lingering as a container nothing manages and nothing updates.
$COMPOSE up -d --remove-orphans

# ── verify, rather than assume ────────────────────────────────────────────
# `up -d` returns as soon as containers are CREATED. A container that starts and
# immediately crashes satisfies it. So does one whose image is fine and whose
# config is wrong.
log "waiting for health"
deadline=$(( $(date +%s) + 120 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  # `mode` is checked, not just a 200. A fixture-mode API answers every request
  # and validates every response over invented data, so "it responded" is not
  # evidence that it is live.
  body="$(curl -fsS --max-time 5 http://localhost:8000/health 2>/dev/null || true)"
  case "$body" in
    *'"mode":"live"'*) ok "api live on all three seams"; break ;;
  esac
  sleep 3
done
case "${body:-}" in
  *'"mode":"live"'*) : ;;
  *'"mode":"fixture"'*)
    bad "api is serving FIXTURES — every request will succeed over invented data"
    bad "check AGENT_MODE, AGENT_DATA_REGISTRY, AGENT_VENUE_REGISTRY in .env"
    exit 1 ;;
  *)
    bad "api did not become healthy within 120s"
    $COMPOSE logs --tail=40 api
    exit 1 ;;
esac

if curl -fsS --max-time 8 -o /dev/null http://localhost:3000/ 2>/dev/null; then
  ok "web responding"
else
  bad "web not responding on :3000"
  $COMPOSE logs --tail=40 web
  exit 1
fi

# ── reclaim ───────────────────────────────────────────────────────────────
# 24 GB disk, and every deploy leaves the previous image behind. Six deploys of
# a Node image is most of the volume. Images only — NOT `system prune --volumes`,
# which would delete agent-state and with it every open Aqua position.
log "reclaim"
docker image prune -f >/dev/null
ok "dangling images removed"
df -h / | tail -1 | sed 's/^/  /'
free -h | sed -n '2p;3p' | sed 's/^/  /'

echo
$COMPOSE ps --format '  {{.Service}}  {{.Status}}'
