#!/usr/bin/env bash
#
# Is the stack actually ready to demo?
#
# Six checks in dependency order. Read-only, safe to re-run, and for every failure it prints the
# cause and the exact command that fixes it — because the expensive failures here do not announce
# themselves:
#
#   * An agent API in fixture mode answers every request and validates every response, over invented
#     numbers. The dApp badge sits on a confident green. Both Lane B and Lane E hit this
#     independently and both flagged it as the thing to check first.
#   * An evicted ollama model surfaces on the next tick as ModelUnavailable — which reads as "the
#     server is down" when it is merely paying a ~2GB reload. It fires precisely when the stack has
#     idled while someone explains the architecture.
#
# Deliberately does NOT start anything. anvil runs in WSL while Python and Node run on the Windows
# host, so a single "up" script would have to shell across that boundary — fragile in exactly the
# moment you would depend on it. This tells you what is wrong; you start it where it belongs.
#
# Usage:
#   ./scripts/preflight.sh              # exits non-zero if anything is not demo-ready
#   ./scripts/preflight.sh --quiet      # summary line only
#
# Uses plain JSON-RPC over curl rather than cast, so it runs unchanged on the Windows host, inside
# WSL, and on macOS. POSIX-friendly bash: no arrays, no jq.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
# .env is a default; an exported variable is an instruction (#45). Matters more here than anywhere:
# a preflight that checks a different node than the one you meant is worse than no preflight.
. "$SCRIPT_DIR/lib/load-env.sh"
load_dotenv

RPC="${ANVIL_RPC_URL:-http://127.0.0.1:8540}"
OLLAMA="${OLLAMA_BASE_URL:-http://localhost:11434/v1}"
OLLAMA_ROOT="$(echo "$OLLAMA" | sed 's#/v1/*$##')"
API="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
WEB="${WEB_URL:-http://localhost:3000}"
USDC="${USDC_ADDRESS:-0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913}"
DEPLOYMENTS="deployments/base-fork.json"
MODEL="${MODEL_NAME:-}"
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

failures=0
warnings=0

ok()   { [ "$QUIET" -eq 1 ] || printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { warnings=$((warnings + 1)); printf "  \033[33m!\033[0m %s\n" "$1"; [ -n "${2:-}" ] && printf "      %s\n" "$2"; return 0; }
bad()  { failures=$((failures + 1)); printf "  \033[31m✗\033[0m %s\n" "$1"; [ -n "${2:-}" ] && printf "      fix: %s\n" "$2"; return 0; }

# Three attempts. A single dropped request must not read as "the fork is down": anvil forking
# against a rate-limited public RPC blips, and WSL's localhost forwarding blips under load. This
# check reported a dead node while the agent API was reading the same fork happily — and a
# demo-readiness gate that cries wolf is a gate people learn to ignore.
rpc() {
  _try=1
  while [ "$_try" -le 3 ]; do
    _out="$(curl -s -m 8 -X POST "$RPC" -H 'Content-Type: application/json' \
      --data "{\"jsonrpc\":\"2.0\",\"method\":\"$1\",\"params\":$2,\"id\":1}" 2>/dev/null)"
    case "$_out" in *'"result"'*) echo "$_out"; return 0 ;; esac
    _try=$((_try + 1))
    [ "$_try" -le 3 ] && sleep 1
  done
  echo "$_out"
}
json_str() { echo "$1" | sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -1; }
json_addr() { sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\(0x[0-9a-fA-F]\{40\}\)\".*/\1/p" "$DEPLOYMENTS" | head -1; }

[ "$QUIET" -eq 1 ] || echo "Preflight — is the stack demo-ready?"
[ "$QUIET" -eq 1 ] || echo

# ── 1. model ──────────────────────────────────────────────────────────────
if curl -s -m 6 "$OLLAMA_ROOT/api/tags" >/dev/null 2>&1; then
  PS="$(curl -s -m 6 "$OLLAMA_ROOT/api/ps" 2>/dev/null)"
  case "$PS" in
    *'"models":[]'*|'') warn "ollama up, but NO MODEL RESIDENT — first tick pays a ~2GB cold load" \
                             "warm it: curl $OLLAMA_ROOT/api/generate -d '{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"keep_alive\":\"30m\",\"stream\":false}'" ;;
    *) ok "ollama up, model resident ($(json_str "$PS" name))" ;;
  esac
else
  bad "ollama unreachable at $OLLAMA_ROOT" "OLLAMA_KEEP_ALIVE=30m ollama serve"
fi

# ── 2. fork ───────────────────────────────────────────────────────────────
CHAIN="$(json_str "$(rpc eth_chainId '[]')" result)"
if [ -n "$CHAIN" ]; then
  BLOCK="$(json_str "$(rpc eth_blockNumber '[]')" result)"
  ok "fork up at $RPC — chain $((16#${CHAIN#0x})), block $((16#${BLOCK#0x}))"
else
  bad "no node at $RPC" "./scripts/anvil-fork.sh   (inside wsl -d Ubuntu-24.04)"
fi

# ── 3. contracts ──────────────────────────────────────────────────────────
if [ ! -f "$DEPLOYMENTS" ]; then
  bad "$DEPLOYMENTS missing" "cd contracts && forge script script/Deploy.s.sol --rpc-url $RPC --broadcast"
elif [ -z "$CHAIN" ]; then
  bad "cannot check contracts — fork is down" "fix the fork first"
else
  FACTORY="$(json_addr VaultFactory)"
  CODE="$(json_str "$(rpc eth_getCode "[\"$FACTORY\",\"latest\"]")" result)"
  if [ -n "$CODE" ] && [ "$CODE" != "0x" ]; then
    ok "contracts deployed — factory $FACTORY"
  else
    bad "factory $FACTORY has no bytecode — anvil restarted since the last deploy" \
        "cd contracts && forge script script/Deploy.s.sol --rpc-url $RPC --broadcast"
  fi
fi

# ── 4. funded accounts ────────────────────────────────────────────────────
SEEDED="${SEED_ACCOUNTS:-}"
ACC="${SEEDED%%,*}"
ACC="${ACC:-0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266}"
if [ -n "$CHAIN" ]; then
  BAL="$(json_str "$(rpc eth_call "[{\"to\":\"$USDC\",\"data\":\"0x70a08231000000000000000000000000${ACC#0x}\"},\"latest\"]")" result)"
  if [ -n "$BAL" ] && [ "$BAL" != "0x0000000000000000000000000000000000000000000000000000000000000000" ]; then
    ok "demo account funded — $((16#${BAL#0x} / 1000000)) USDC"
  else
    bad "demo account $ACC holds no USDC" "./scripts/seed-fork.sh"
  fi
fi

# ── 5. agent API — the one that lies ──────────────────────────────────────
HEALTH="$(curl -s -m 8 "$API/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
  bad "agent API unreachable at $API" "uv run uvicorn agent.api.app:app --port 8000"
else
  MODE="$(json_str "$HEALTH" mode)"
  DATA="$(json_str "$HEALTH" data_registry)"
  VENUE="$(json_str "$HEALTH" venue_registry)"
  if [ "$MODE" = "live" ] && [ "$DATA" != "fixture" ] && [ "$VENUE" != "fixture" ]; then
    ok "agent API live on all three seams — data=$DATA venue=$VENUE"
  else
    bad "agent API is serving FIXTURES (mode=$MODE data=$DATA venue=$VENUE) — every request will succeed over invented numbers" \
        "set AGENT_MODE=live, AGENT_DATA_REGISTRY, AGENT_VENUE_REGISTRY in .env and RESTART the API"
  fi
fi

# ── 6. dApp ───────────────────────────────────────────────────────────────
if curl -s -m 8 -o /dev/null "$WEB" 2>/dev/null; then
  ok "dApp responding at $WEB"
else
  warn "dApp not responding at $WEB" "pnpm --filter @curator/web dev   (only needed for the browser demo)"
fi

echo
if [ "$failures" -gt 0 ]; then
  echo "NOT demo-ready — $failures blocking, $warnings warning(s)." >&2
  exit 1
fi
[ "$warnings" -gt 0 ] && { echo "Demo-ready with $warnings warning(s)."; exit 0; }
echo "Demo-ready."
