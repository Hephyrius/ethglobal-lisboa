#!/usr/bin/env bash
#
# Verify deployed contracts on Blockscout so judges can read the source.
#
# WHY BLOCKSCOUT AND NOT ETHERSCAN (cross-lane request #23): there is no free Etherscan path for Base.
# The V2 API rejects this chain outright — "Free API access is not supported for this chain" — and
# api.basescan.org V1 now refuses with "You are using a deprecated V1 endpoint". Blockscout needs no
# API key at all and produces the same outcome: readable, verified source behind a public link.
#
# Reads addresses from deployments/<network>.json, so it verifies whatever was actually deployed
# rather than whatever someone remembered to paste.
#
# Usage:
#   ./script/verify.sh                      # verify the base-mainnet deployment
#   ./script/verify.sh base-sepolia         # a different network
#   VERIFIER_URL=https://... ./script/verify.sh
#
# POSIX-friendly bash: no arrays, no jq — runs under the bash 3.2 that ships with macOS.

set -eu

cd "$(dirname "$0")/.."

NETWORK="${1:-base-mainnet}"
DEPLOYMENTS="../deployments/${NETWORK}.json"

# Blockscout's Base instance. Override for another chain or a self-hosted instance.
VERIFIER_URL="${VERIFIER_URL:-https://base.blockscout.com/api}"

command -v forge >/dev/null 2>&1 || {
  echo "forge not found. Windows: run inside 'wsl -d Ubuntu-24.04'." >&2
  exit 1
}

[ -f "$DEPLOYMENTS" ] || {
  echo "No deployment found at ${DEPLOYMENTS#../} (repo root)" >&2
  echo "  Deploy first:  DEPLOY_NETWORK=${NETWORK} forge script script/Deploy.s.sol --broadcast" >&2
  exit 1
}

# Pull an address out of the deployments JSON without jq (not installed on a stock macOS).
# Matches "Key": "0x...." and prints the address.
json_address() {
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\(0x[0-9a-fA-F]\{40\}\)\".*/\1/p" "$DEPLOYMENTS" | head -1
}

IMPLEMENTATION="$(json_address CuratedVaultImplementation)"
FACTORY="$(json_address VaultFactory)"

[ -n "$IMPLEMENTATION" ] || { echo "CuratedVaultImplementation missing from $DEPLOYMENTS" >&2; exit 1; }
[ -n "$FACTORY" ] || { echo "VaultFactory missing from $DEPLOYMENTS" >&2; exit 1; }

echo "network         $NETWORK"
echo "verifier        blockscout ($VERIFIER_URL)"
echo "implementation  $IMPLEMENTATION"
echo "factory         $FACTORY"
echo

verify() {
  # $1 address, $2 contract path:name, $3.. extra flags
  addr="$1"; target="$2"; shift 2
  echo "→ $target  $addr"
  forge verify-contract "$addr" "$target" \
    --verifier blockscout \
    --verifier-url "$VERIFIER_URL" \
    --watch "$@" || echo "  ! verification failed for $target — see the note at the bottom of this script"
  echo
}

# CuratedVault's constructor takes no arguments (it only calls _disableInitializers), so this one
# needs nothing extra. Verify it first: it is the contract whose source actually matters to a reader,
# since every vault is a clone delegating to it.
verify "$IMPLEMENTATION" "src/CuratedVault.sol:CuratedVault"

# VaultFactory's constructor takes (address, address[], TokenValuation[], uint256). Rather than
# hand-encoding a struct array, let Foundry recover them from the deployment transaction.
verify "$FACTORY" "src/VaultFactory.sol:VaultFactory" --guess-constructor-args

cat <<'NOTE'
Vault instances are EIP-1167 minimal proxies. There is no source to verify for a clone — Blockscout
detects the proxy pattern and shows the implementation's verified source, which is why verifying
CuratedVault above is what makes every vault readable.

If --guess-constructor-args fails for the factory, encode them explicitly. The values are in
deployments/<network>.json (owner = whoever ran the deploy, targets = executeAllowlist.targets,
valuations = [(WETH, ChainlinkEthUsdFeed)], priceMaxAge = priceMaxAge):

  cast abi-encode "c(address,address[],(address,address)[],uint256)" \
    <owner> "[<target>,...]" "[(<weth>,<feed>)]" <priceMaxAge>

then pass the result as --constructor-args <hex>.
NOTE
