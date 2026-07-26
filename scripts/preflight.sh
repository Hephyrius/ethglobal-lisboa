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
# `${x,,}` is bash 4. macOS ships bash 3.2, where it is a syntax error at PARSE
# time — the whole script would refuse to run, on the one machine that takes over
# at the handoff. tr is portable and this is not a hot path.
lower() { echo "$1" | tr 'A-Z' 'a-z'; }

# ── localhost is not one place on this machine ────────────────────────────────────────────────
#
# anvil runs inside WSL while ollama, the API and the dApp run on the Windows host, so a
# `localhost` URL means a different machine depending on which side this script is run from. Run
# from WSL, preflight reported ollama AND the agent API as unreachable while both were serving
# happily — two blocking failures, zero real problems, at exactly the moment someone would trust
# it. A gate that cries wolf is a gate people learn to ignore.
#
# So: try the URL as given, and if that fails while we are inside WSL, try the Windows host from
# the default route. Report which one answered, because "reachable, but only via 172.23.112.1" is
# a different fact from "reachable".

WSL_HOST=""
if grep -qi microsoft /proc/version 2>/dev/null; then
  WSL_HOST="$(ip route show default 2>/dev/null | awk '{print $3}' | head -1)"
fi

#: Echoes a reachable form of $1, or nothing. Sets REACHED_VIA to "" or "windows host".
REACHED_VIA=""
reachable_url() {
  _url="$1"; _path="${2:-}"
  REACHED_VIA=""
  if curl -s -m 6 -o /dev/null "$_url$_path" 2>/dev/null; then echo "$_url"; return 0; fi
  case "$_url" in
    *localhost*|*127.0.0.1*)
      [ -n "$WSL_HOST" ] || return 1
      _alt="$(echo "$_url" | sed -e "s#localhost#$WSL_HOST#" -e "s#127\.0\.0\.1#$WSL_HOST#")"
      if curl -s -m 6 -o /dev/null "$_alt$_path" 2>/dev/null; then
        REACHED_VIA="windows host"
        echo "$_alt"
        return 0
      fi ;;
  esac
  return 1
}

[ "$QUIET" -eq 1 ] || echo "Preflight — is the stack demo-ready?"
[ "$QUIET" -eq 1 ] || echo

# The agent's own health answer is fetched first because check 1 needs it. It is also the only
# witness that matters for the model: the question is not whether PREFLIGHT can reach ollama, it is
# whether the AGENT can. Those differ whenever this runs from a different side of the WSL boundary
# than the API does.
API_URL_OK="$(reachable_url "$API" "/health")" || API_URL_OK=""
API_VIA="$REACHED_VIA"
HEALTH=""
[ -n "$API_URL_OK" ] && HEALTH="$(curl -s -m 10 "$API_URL_OK/health" 2>/dev/null)"

# ── 1. model ──────────────────────────────────────────────────────────────
OLLAMA_OK="$(reachable_url "$OLLAMA_ROOT" "/api/tags")" || OLLAMA_OK=""
OLLAMA_VIA="$REACHED_VIA"
if [ -n "$OLLAMA_OK" ]; then
  PS="$(curl -s -m 6 "$OLLAMA_OK/api/ps" 2>/dev/null)"
  case "$PS" in
    *'"models":[]'*|'') warn "ollama up, but NO MODEL RESIDENT — first tick pays a ~2GB cold load" \
                             "warm it: curl $OLLAMA_OK/api/generate -d '{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"keep_alive\":\"30m\",\"stream\":false}'" ;;
    *) ok "ollama up, model resident ($(json_str "$PS" name))${OLLAMA_VIA:+ — via the $OLLAMA_VIA}" ;;
  esac
elif [ "$(json_str "$HEALTH" model_reachable)" = "true" ] || \
     case "$HEALTH" in *'"model_reachable":true'*) true ;; *) false ;; esac; then
  # ollama binds 127.0.0.1 by default, so from inside WSL it is genuinely unreachable — and
  # genuinely irrelevant, because the agent that uses it runs beside it on the host and says so.
  # Believing the direct probe here would block a demo that works.
  warn "ollama not reachable from here, but the agent API reports the model IS reachable" \
       "expected when preflight runs inside WSL and ollama binds 127.0.0.1 on the host — not a blocker"
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
  # The rpc call is hoisted into its own variable rather than nested directly inside
  # json_str's own $( ). Under the bash 3.2 that macOS still ships, a $( ) containing
  # escaped quotes, nested inside another $( ), loses those escapes — which leaves the
  # `{...}` here unquoted, so brace expansion splits `[{A,B},"latest"]` into TWO words
  # and rpc gets called twice with malformed params. It returns no `result`, BAL comes
  # back empty, and preflight reports a funded account as holding nothing. The other rpc
  # calls in this file survive only because none of them contain braces.
  #
  # Verified on macOS bash 3.2.57: nested fails, hoisted works. Do not re-inline this.
  BAL_RAW="$(rpc eth_call "[{\"to\":\"$USDC\",\"data\":\"0x70a08231000000000000000000000000${ACC#0x}\"},\"latest\"]")"
  BAL="$(json_str "$BAL_RAW" result)"
  if [ -n "$BAL" ] && [ "$BAL" != "0x0000000000000000000000000000000000000000000000000000000000000000" ]; then
    ok "demo account funded — $((16#${BAL#0x} / 1000000)) USDC"
  else
    bad "demo account $ACC holds no USDC" "./scripts/seed-fork.sh"
  fi
fi

# ── 4b. the agent key can actually write ──────────────────────────────────
# Reads work with any key. Writes need AGENT_ROLE on the vault and gas, and when
# either is missing NOTHING upstream looks wrong: /health is green, the model
# reasons correctly, a decision passes all six validation layers, and only the
# final broadcast fails — as "Insufficient funds for gas" or as a bare revert on
# an AccessControl check, neither of which names the cause.
#
# It happened here: a credential rotation swept AGENT_PRIVATE_KEY along with the
# real secrets, replacing anvil account #1 with a fresh mainnet key that holds
# neither role nor gas on the fork. Every execution failed and the whole stack
# reported healthy. This is failure mode #11 in docs/runbook.md, and it costs
# nothing to catch here instead.
EXPECTED_AGENT="$(json_addr agent)"
if [ -n "$CHAIN" ] && [ -n "$EXPECTED_AGENT" ]; then
  GAS="$(json_str "$(rpc eth_getBalance "[\"$EXPECTED_AGENT\",\"latest\"]")" result)"
  if [ "$GAS" = "0x0" ] || [ -z "$GAS" ]; then
    bad "the vault's agent $EXPECTED_AGENT holds no ETH — every execution fails on gas" \
        "./scripts/seed-fork.sh"
  # `cast` is how the configured key is turned into an address; without Foundry on
  # PATH the gas check above still runs and only the identity half is skipped.
  elif command -v cast >/dev/null 2>&1 && [ -n "${AGENT_PRIVATE_KEY:-}" ]; then
    CONFIGURED="$(cast wallet address --private-key "$AGENT_PRIVATE_KEY" 2>/dev/null || echo "")"
    if [ -z "$CONFIGURED" ]; then
      warn "AGENT_PRIVATE_KEY is set but cast could not read it" "check it is a 0x-prefixed 32-byte key"
    elif [ "$(lower "$CONFIGURED")" = "$(lower "$EXPECTED_AGENT")" ]; then
      ok "agent key matches the vault's agent ($EXPECTED_AGENT) and holds gas"
    else
      bad "AGENT_PRIVATE_KEY is $CONFIGURED but the vault's agent is $EXPECTED_AGENT — every write will revert" \
          "on a fork this should be anvil account #1; see .env.example"
    fi
  else
    ok "vault agent $EXPECTED_AGENT funded for gas (key identity unchecked — cast not on PATH)"
  fi
fi

# ── 5. agent API — the one that lies ──────────────────────────────────────
if [ -z "$HEALTH" ]; then
  bad "agent API unreachable at $API" "uv run uvicorn agent.api.app:app --port 8000"
else
  MODE="$(json_str "$HEALTH" mode)"
  DATA="$(json_str "$HEALTH" data_registry)"
  VENUE="$(json_str "$HEALTH" venue_registry)"
  if [ "$MODE" = "live" ] && [ "$DATA" != "fixture" ] && [ "$VENUE" != "fixture" ]; then
    ok "agent API live on all three seams — data=$DATA venue=$VENUE${API_VIA:+ (via the $API_VIA)}"
  else
    bad "agent API is serving FIXTURES (mode=$MODE data=$DATA venue=$VENUE) — every request will succeed over invented numbers" \
        "set AGENT_MODE=live, AGENT_DATA_REGISTRY, AGENT_VENUE_REGISTRY in .env and RESTART the API"
  fi
fi

# ── 6. dApp ───────────────────────────────────────────────────────────────
WEB_OK="$(reachable_url "$WEB" "")" || WEB_OK=""
if [ -n "$WEB_OK" ]; then
  ok "dApp responding at $WEB_OK${REACHED_VIA:+ — via the $REACHED_VIA}"
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
