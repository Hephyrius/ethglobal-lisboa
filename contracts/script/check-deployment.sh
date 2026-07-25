#!/usr/bin/env bash
#
# Does the deployed code match the source in this repo?
#
# Answers one question that nothing else does: contract source can be edited after a deploy, and
# every downstream "verified against the deployed vault" claim silently becomes a claim about
# different code. Three other lanes assert against the fork deployment, the submission points judges
# at this source, and a demo runs on whatever is actually deployed — so this is worth being able to
# check in ten seconds rather than reasoning about.
#
# Run it before the demo, before submitting, and after any change under src/.
#
# Usage:
#   ./script/check-deployment.sh                                   # base-fork, via ANVIL_RPC_URL
#   ./script/check-deployment.sh base-mainnet "$BASE_RPC_URL"
#
# Exits non-zero on a mismatch, so it also works as a pre-demo gate.
#
# POSIX-friendly bash: no arrays, no jq — runs under the bash 3.2 macOS ships.

set -eu

cd "$(dirname "$0")/.."

NETWORK="${1:-base-fork}"
RPC="${2:-${ANVIL_RPC_URL:-http://127.0.0.1:8540}}"
DEPLOYMENTS="../deployments/${NETWORK}.json"

command -v forge >/dev/null 2>&1 || {
  echo "forge not found. Windows: run inside 'wsl -d Ubuntu-24.04'." >&2
  exit 1
}

[ -f "$DEPLOYMENTS" ] || { echo "No deployment at ${DEPLOYMENTS#../} (repo root)" >&2; exit 1; }

json_address() {
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\(0x[0-9a-fA-F]\{40\}\)\".*/\1/p" "$DEPLOYMENTS" | head -1
}

IMPLEMENTATION="$(json_address CuratedVaultImplementation)"
FACTORY="$(json_address VaultFactory)"

echo "network  $NETWORK"
echo "rpc      $RPC"
echo

forge build >/dev/null

TMP="${TMPDIR:-/tmp}"
status=0

# The implementation must match byte for byte. It has no immutables, and `bytecode_hash = "none"` in
# foundry.toml keeps the metadata hash out of the bytecode, so identical source compiles to identical
# code on any machine. This is the check that matters: every vault is an EIP-1167 clone delegating
# here, so this bytecode *is* the vault logic.
cast code "$IMPLEMENTATION" --rpc-url "$RPC" > "$TMP/dep-impl.hex"
forge inspect CuratedVault deployedBytecode --json | tr -d '"' > "$TMP/loc-impl.hex"

if cmp -s "$TMP/dep-impl.hex" "$TMP/loc-impl.hex"; then
  echo "✓ CuratedVault  $IMPLEMENTATION"
  echo "  deployed bytecode is identical to the committed source"
else
  echo "✗ CuratedVault  $IMPLEMENTATION"
  echo "  MISMATCH — the deployed vault is NOT running this source."
  echo "  Either redeploy, or stop citing the deployment as evidence for this code."
  status=1
fi
echo

# VaultFactory holds `implementation` as an immutable, which is baked into the deployed bytecode but
# left as zeros in the compiler artifact. A small, fixed number of differing bytes is therefore
# expected and correct; anything beyond that means the source moved.
cast code "$FACTORY" --rpc-url "$RPC" > "$TMP/dep-fac.hex"
forge inspect VaultFactory deployedBytecode --json | tr -d '"' > "$TMP/loc-fac.hex"

dep_len=$(wc -c < "$TMP/dep-fac.hex" | tr -d ' ')
loc_len=$(wc -c < "$TMP/loc-fac.hex" | tr -d ' ')

if [ "$dep_len" != "$loc_len" ]; then
  echo "✗ VaultFactory  $FACTORY"
  echo "  length differs ($dep_len vs $loc_len) — the source has changed since deployment"
  status=1
else
  # Count differing hex characters. Each embedded address occurrence accounts for 40 of them.
  diffs=$(cmp -l "$TMP/dep-fac.hex" "$TMP/loc-fac.hex" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$diffs" -le 80 ]; then
    echo "✓ VaultFactory  $FACTORY"
    echo "  $diffs hex chars differ — the immutable \`implementation\` address, as expected"
  else
    echo "✗ VaultFactory  $FACTORY"
    echo "  $diffs hex chars differ, more than the immutable can account for (max 80)"
    status=1
  fi
fi

echo
if [ "$status" -eq 0 ]; then
  echo "Deployment matches the source in this repo."
else
  echo "DEPLOYMENT DOES NOT MATCH THIS SOURCE." >&2
fi
exit "$status"
