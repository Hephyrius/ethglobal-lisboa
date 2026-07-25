#!/usr/bin/env bash
# Base mainnet fork for local development.
#
# Windows: run inside `wsl -d Ubuntu-24.04` — NOT the default Ubuntu-20.04,
# whose glibc 2.31 is too old for Foundry's prebuilt binaries.
#
# Binds 0.0.0.0 deliberately: the Python harness and the browser run on the
# Windows host while anvil runs in WSL, and 127.0.0.1 would be unreachable
# from there. On macOS this is a no-op.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
# .env is a default; an exported variable is an instruction (#45).
. "$SCRIPT_DIR/lib/load-env.sh"
load_dotenv

: "${BASE_RPC_URL:?set BASE_RPC_URL in .env — must be ARCHIVE-CAPABLE.
   The public mainnet.base.org is rate-limited and will crawl or fail under
   forking. Use an Alchemy/QuickNode/dRPC endpoint. See docs/setup.md.}"

PORT="${ANVIL_PORT:-8540}"
# Pinning the block makes runs reproducible and lets the fork cache warm, which
# matters a lot when five lanes are hitting it. Unset to track chain head.
BLOCK_ARG=""
[ -n "${FORK_BLOCK_NUMBER:-}" ] && BLOCK_ARG="--fork-block-number ${FORK_BLOCK_NUMBER}"

command -v anvil >/dev/null 2>&1 || {
  echo "anvil not found." >&2
  echo "  Windows: are you in 'wsl -d Ubuntu-24.04'? See docs/setup.md §2." >&2
  exit 1
}

echo "Forking Base mainnet on port ${PORT} (chain id 8453)"
echo "  Aqua    0x499943e74fb0ce105688beee8ef2abec5d936d31"
echo "  SwapVM  0x8fdd04dbf6111437b44bbca99c28882434e0958f"
echo "  USDC    0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

exec anvil \
  --fork-url "${BASE_RPC_URL}" \
  ${BLOCK_ARG} \
  --chain-id 8453 \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --accounts 10 \
  --balance 10000
