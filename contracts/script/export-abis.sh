#!/usr/bin/env bash
#
# Publish flat ABI arrays to contracts/abis/ — the stable, documented path Lanes B, D and E import.
#
# `out/**` is committed too, but an artifact there is a large object with the ABI nested under an
# `.abi` key alongside bytecode, storage layout and metadata. A consumer would have to know the
# Foundry artifact layout and reach into it. `abis/CuratedVault.json` is just the array, which is
# what web3.py and viem want handed to them.
#
# Re-run after any change to a public signature, and commit the result — a downstream lane building
# calldata against a stale ABI fails at run time with an unhelpful error.
#
# Usage:
#   ./script/export-abis.sh                       # the published set
#   ./script/export-abis.sh CuratedVault          # just one
#
# POSIX-friendly bash: no arrays, so it also runs under the bash 3.2 that ships with macOS.

set -eu

cd "$(dirname "$0")/.."

CONTRACTS="$*"
[ -z "$CONTRACTS" ] && CONTRACTS="CuratedVault VaultFactory"

command -v forge >/dev/null 2>&1 || {
  echo "forge not found." >&2
  echo "  Windows: run inside 'wsl -d Ubuntu-24.04' — NOT the default 20.04 distro." >&2
  echo "  Install: curl -L https://foundry.paradigm.xyz | bash && foundryup" >&2
  exit 1
}

forge build

mkdir -p abis
for name in $CONTRACTS; do
  forge inspect "$name" abi --json > "abis/$name.json"
  echo "✓ abis/$name.json"
done

echo
echo "Committed ABIs are the integration surface — see contracts/README.md."
