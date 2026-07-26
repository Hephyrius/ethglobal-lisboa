#!/usr/bin/env bash
# Keep the stack alive without a human watching it.
#
# `restart: unless-stopped` in docker-compose.yml already handles the easy case:
# a process that exits comes back, and everything comes back after a reboot.
# What it does NOT handle is the case that actually bites — **a container that
# is running and wedged.** Docker runs the healthcheck, marks the container
# `unhealthy`, and then does nothing at all with that information. `docker
# compose ps` shows the problem and no one is looking at `docker compose ps`.
#
# So this fills exactly that gap, and deliberately nothing more.
#
# ## What it will not do
#
# **It will not restart on one bad probe.** A single failed check during a
# 15-eth_call vault read on a 1 vCPU box is normal. Restarting on it turns a
# slow second into ten seconds of hard downtime — which is precisely the
# failure mode that ruined a recording here: four API restarts in twenty
# minutes, each one reaching the browser as `TypeError: Failed to fetch`.
# CONSEC_FAILS consecutive checks are required before it acts.
#
# **It will not loop.** COOLDOWN seconds must pass between restarts of the same
# service. A container that is crash-looping for a real reason (bad env, failed
# migration) must stay down and visible rather than be papered over — a
# watchdog that hides a genuine fault is worse than no watchdog.
#
# **It will not restart over an upstream failure.** The most common way this API
# "goes down" is the public RPC answering 429, which leaves the process
# perfectly healthy and every vault read failing. Restarting cannot fix a rate
# limit and would only add downtime, so the HTTP probe hits /health — which
# touches no chain — and never a vault route.
#
# Install (idempotent, does not touch running containers):
#     bash /srv/scipio/watchdog.sh --install
#
# Check what it has been doing:
#     journalctl -u scipio-watchdog --since -2h
set -eu

COMPOSE_DIR="${COMPOSE_DIR:-/srv/scipio}"
STATE_DIR="${STATE_DIR:-/var/lib/scipio-watchdog}"
PROBE_URL="${PROBE_URL:-https://api.scipio.capital/health}"
# Checked for both "gone" and "wedged".
SERVICES="api caddy"
# Checked ONLY for "gone", never for `unhealthy`.
#
# The ticker runs no server but inherits the API image's healthcheck, which
# probes :8000 — so Docker marks a perfectly good loop unhealthy forever.
# `healthcheck: disable: true` in docker-compose.yml fixes that, but only for a
# container recreated from the current file, and recreating one mid-demo is the
# opposite of what a watchdog is for. Treating it as wedged would restart it
# every COOLDOWN seconds indefinitely: a watchdog manufacturing the outage it
# exists to prevent.
DOWN_ONLY_SERVICES="ticker"
CONSEC_FAILS="${CONSEC_FAILS:-2}"
COOLDOWN="${COOLDOWN:-300}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-20}"

log() { echo "[watchdog] $*"; }

# ─────────────────────────────────────────────────────────────────────────
# Install
# ─────────────────────────────────────────────────────────────────────────

install_units() {
  install -d "$STATE_DIR"
  install -m 0755 "$0" /usr/local/bin/scipio-watchdog.sh

  cat >/etc/systemd/system/scipio-watchdog.service <<'UNIT'
[Unit]
Description=Restart wedged scipio containers
# Docker must be up, or every check fails and the counter climbs against a
# machine that is merely still booting.
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/scipio-watchdog.sh
UNIT

  cat >/etc/systemd/system/scipio-watchdog.timer <<'UNIT'
[Unit]
Description=Check scipio health every minute

[Timer]
# OnCalendar, not OnUnitActiveSec. For a `oneshot` service the latter re-arms
# from the service's own last activation, and systemd would not schedule a next
# elapse at all — `systemctl list-timers` showed the timer active with NEXT set
# to `-`, which is a watchdog that runs exactly once and then never again. That
# fails silently and in the same direction as the problem it guards against.
OnCalendar=minutely
# Catch up at most once after the machine has been off, rather than replaying
# every missed minute.
Persistent=false
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

  systemctl daemon-reload
  systemctl enable --now scipio-watchdog.timer
  log "installed; timer active"
  systemctl list-timers scipio-watchdog.timer --no-pager || true
}

# ─────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────

compose() { docker compose --project-directory "$COMPOSE_DIR" -f "$COMPOSE_DIR/docker-compose.yml" "$@"; }

# running | unhealthy | down
service_status() {
  svc="$1"
  cid="$(compose ps -q "$svc" 2>/dev/null || true)"
  [ -n "$cid" ] || { echo down; return; }

  state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
  [ "$state" = "running" ] || { echo down; return; }

  # `{{.State.Health}}` is nil for a container with no healthcheck — the ticker,
  # which disables it. Printing the struct and matching gives "no healthcheck"
  # and "healthy" the same answer without a second inspect.
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
  case "$health" in
    unhealthy) echo unhealthy ;;
    *)         echo running ;;
  esac
}

counter_path() { echo "$STATE_DIR/fail-$1"; }
stamp_path()   { echo "$STATE_DIR/restarted-$1"; }

read_int() { [ -f "$1" ] && cat "$1" 2>/dev/null || echo 0; }

cooled_down() {
  svc="$1"
  last="$(read_int "$(stamp_path "$svc")")"
  now="$(date +%s)"
  [ $((now - last)) -ge "$COOLDOWN" ]
}

recover() {
  svc="$1" why="$2"
  if ! cooled_down "$svc"; then
    log "$svc $why but restarted <${COOLDOWN}s ago; leaving it alone"
    return
  fi
  log "RESTARTING $svc ($why)"
  date +%s >"$(stamp_path "$svc")"
  # `up -d` rather than `restart`: it also covers the container being absent
  # entirely, which `restart` cannot, and it is a no-op for one already running
  # from the current config.
  compose up -d "$svc" >/dev/null 2>&1 || compose restart "$svc" >/dev/null 2>&1 || log "  recovery command failed for $svc"
  echo 0 >"$(counter_path "$svc")"
}

check_service() {
  svc="$1" mode="${2:-full}"
  status="$(service_status "$svc")"
  cfile="$(counter_path "$svc")"

  [ "$mode" = "down-only" ] && [ "$status" = "unhealthy" ] && status=running

  if [ "$status" = "running" ]; then
    echo 0 >"$cfile"
    return
  fi

  fails=$(( $(read_int "$cfile") + 1 ))
  echo "$fails" >"$cfile"
  log "$svc is $status ($fails/$CONSEC_FAILS)"
  [ "$fails" -ge "$CONSEC_FAILS" ] && recover "$svc" "$status"
  return 0
}

# The end-to-end path, which the per-container checks cannot see: TLS, Caddy's
# upstream resolution, and the app all at once. /health only, never a vault
# route — see the header on why an upstream 429 must not trigger a restart.
check_endpoint() {
  cfile="$(counter_path endpoint)"
  if curl -fsS --max-time "$PROBE_TIMEOUT" -o /dev/null "$PROBE_URL" 2>/dev/null; then
    echo 0 >"$cfile"
    return
  fi

  fails=$(( $(read_int "$cfile") + 1 ))
  echo "$fails" >"$cfile"
  log "probe $PROBE_URL failed ($fails/$CONSEC_FAILS)"
  if [ "$fails" -ge "$CONSEC_FAILS" ]; then
    # Order matters: an unreachable endpoint with both containers running is
    # usually Caddy holding a stale upstream IP after the API got a new one.
    # Restarting the API first would change that IP again and guarantee a
    # second failed round.
    recover caddy "endpoint unreachable"
    recover api "endpoint unreachable"
    echo 0 >"$cfile"
  fi
  return 0
}

main() {
  [ "${1:-}" = "--install" ] && { install_units; return; }
  install -d "$STATE_DIR"
  for svc in $SERVICES; do check_service "$svc" full; done
  for svc in $DOWN_ONLY_SERVICES; do check_service "$svc" down-only; done
  check_endpoint
}

main "$@"
