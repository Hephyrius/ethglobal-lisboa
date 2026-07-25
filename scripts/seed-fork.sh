#!/usr/bin/env bash
#
# Put USDC and ETH into demo accounts on a freshly started Base fork.
#
# Why this exists: contracts/script/Deploy.s.sol deploys the factory and a vault but never funds
# anything, so a fresh fork has ETH on the anvil accounts and no USDC anywhere. Until this runs,
# nobody can deposit and the demo cannot start. That gap is why the current demo vault was funded by
# hand, and why its state lives only inside one long-running anvil process.
#
# How: impersonate a large USDC holder and transfer. The tempting alternative — writing the balance
# slot with anvil_setStorageAt — is wrong here: USDC on Base is a proxy, a hardcoded slot breaks
# silently on upgrade, and the failure presents as "the transfer didn't happen".
#
# Idempotent: USDC is TOPPED UP to the target, never blindly added, so re-running is a no-op. A demo
# gets re-seeded more than once.
#
# Usage:
#   ./scripts/seed-fork.sh                                  # anvil accounts 0-2, 100k USDC each
#   ./scripts/seed-fork.sh --usdc 5000                      # smaller float
#   ./scripts/seed-fork.sh --accounts 0xAbC...,0xDeF...     # explicit addresses
#   ./scripts/seed-fork.sh --rpc http://127.0.0.1:8540
#
# Exits non-zero if the fork is unreachable or the whale is dry, so it works as a gate.
#
# POSIX-friendly bash: no arrays, no jq, no arithmetic on wei (100 ETH overflows a 64-bit shell int)
# — runs under the bash 3.2 macOS ships.

set -eu

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

RPC="${ANVIL_RPC_URL:-http://127.0.0.1:8540}"
USDC="${USDC_ADDRESS:-0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913}"

# Morpho Blue on Base. Chosen by inspection, not reputation: it held ~179M USDC at the fork block,
# orders of magnitude more than a demo needs, and it is a protocol contract so the balance will not
# vanish between fork blocks. Override with --whale if it ever runs dry.
WHALE="${USDC_WHALE:-0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb}"

# anvil accounts 0, 1, 2 — deployer/depositor, agent (AGENT_ROLE), spare second depositor.
ACCOUNTS="${SEED_ACCOUNTS:-0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266,0x70997970C51812dc3A010C7d01b50e0d17dc79C8,0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC}"

USDC_TARGET="100000"                 # human units
ETH_TARGET_HEX="0x56BC75E2D63100000" # 100 ether, as hex — never arithmetic on wei in shell

while [ $# -gt 0 ]; do
  case "$1" in
    --rpc)      RPC="$2"; shift 2 ;;
    --accounts) ACCOUNTS="$2"; shift 2 ;;
    --usdc)     USDC_TARGET="$2"; shift 2 ;;
    --whale)    WHALE="$2"; shift 2 ;;
    -h|--help)  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v cast >/dev/null 2>&1 || {
  echo "cast not found. Windows: run inside 'wsl -d Ubuntu-24.04'. See docs/setup.md §2." >&2
  exit 1
}

cast chain-id --rpc-url "$RPC" >/dev/null 2>&1 || {
  echo "No node at $RPC — start the fork first:" >&2
  echo "  ./scripts/anvil-fork.sh" >&2
  exit 1
}

# USDC is 6-decimal, so raw amounts stay well inside a 64-bit int even at 179M. Safe to compute here.
USDC_TARGET_RAW=$((USDC_TARGET * 1000000))

usdc_balance() {
  cast call "$USDC" "balanceOf(address)(uint256)" "$1" --rpc-url "$RPC" | awk '{print $1}'
}

echo "rpc     $RPC"
echo "usdc    $USDC"
echo "whale   $WHALE"
echo "target  ${USDC_TARGET} USDC per account"
echo

WHALE_BAL="$(usdc_balance "$WHALE")"
if [ "$WHALE_BAL" -lt "$USDC_TARGET_RAW" ]; then
  echo "Whale $WHALE holds $((WHALE_BAL / 1000000)) USDC, less than one account's target." >&2
  echo "Pass another with --whale, or set USDC_WHALE in .env." >&2
  exit 1
fi

cast rpc anvil_impersonateAccount "$WHALE" --rpc-url "$RPC" >/dev/null
# Impersonation does not grant ETH, and the whale pays gas for every transfer below.
cast rpc anvil_setBalance "$WHALE" "$ETH_TARGET_HEX" --rpc-url "$RPC" >/dev/null

seeded=0
OLDIFS="$IFS"
IFS=','
for ACCOUNT in $ACCOUNTS; do
  IFS="$OLDIFS"

  # Unconditional: setBalance to a fixed target is already idempotent, and comparing wei would mean
  # 64-bit arithmetic on values above 9.2e18.
  cast rpc anvil_setBalance "$ACCOUNT" "$ETH_TARGET_HEX" --rpc-url "$RPC" >/dev/null

  USDC_NOW="$(usdc_balance "$ACCOUNT")"
  if [ "$USDC_NOW" -lt "$USDC_TARGET_RAW" ]; then
    SHORTFALL=$((USDC_TARGET_RAW - USDC_NOW))
    cast send "$USDC" "transfer(address,uint256)" "$ACCOUNT" "$SHORTFALL" \
      --from "$WHALE" --unlocked --rpc-url "$RPC" >/dev/null
    printf "  %s  +%s USDC\n" "$ACCOUNT" "$((SHORTFALL / 1000000))"
    seeded=$((seeded + 1))
  else
    printf "  %s  already at %s USDC\n" "$ACCOUNT" "$((USDC_NOW / 1000000))"
  fi

  IFS=','
done
IFS="$OLDIFS"

cast rpc anvil_stopImpersonatingAccount "$WHALE" --rpc-url "$RPC" >/dev/null

echo
if [ "$seeded" -eq 0 ]; then
  echo "Already seeded — nothing to do."
else
  echo "Seeded $seeded account(s)."
fi
