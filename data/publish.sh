#!/usr/bin/env bash
#
# Publish the three curator packages to PyPI, bottom of the dependency chain
# first. Lane C owns this; the reasoning and the manual equivalents are in
# PUBLISHING.md.
#
# Why a script rather than the four commands in the doc: the ORDER is
# load-bearing (curator-mcp cannot resolve until curator-data is up, which
# cannot resolve until curator-schema is), a PyPI version can never be
# re-uploaded once taken, and this will most likely be run by someone tired.
# The dry run below is the part that makes a mistake cheap.
#
# POSIX bash 3.2 (macOS ships it), set -eu, no arrays, no jq — matching
# contracts/script/check-deployment.sh. Non-zero exit so it doubles as a gate.
#
# Usage:
#   ./data/publish.sh                 # build + verify only, uploads nothing
#   ./data/publish.sh --publish       # build, verify, then upload
#   ./data/publish.sh --publish --test-pypi
#
# Needs UV_PUBLISH_TOKEN in the environment (or .env) for --publish.

set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIST="$REPO_ROOT/dist"
PUBLISH=0
INDEX=""
ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --publish)   PUBLISH=1 ;;
    --test-pypi) INDEX="https://test.pypi.org/legacy/" ;;
    --yes)       ASSUME_YES=1 ;;   # non-interactive; the caller has confirmed
    -h|--help)   sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

# ── 1. build, bottom of the chain first ──────────────────────────────────
echo "==> Building distributions into dist/"
rm -rf "$DIST"
uv build --out-dir "$DIST" packages/schema/python
uv build --out-dir "$DIST" data
uv build --out-dir "$DIST" data/curator_mcp
echo

# ── 2. prove the wheels stand alone BEFORE anything is uploaded ──────────
#
# The failure this catches: a wheel whose metadata still points at local path
# sources resolves fine here and is unusable for everyone else. Installing
# from --find-links with no repo on the path is the only honest check, and a
# PyPI version number is permanent, so it has to happen first.
echo "==> Verifying the wheels resolve with no repo present"
VERIFY_VENV=$(mktemp -d)/venv
uv venv --python 3.10 "$VERIFY_VENV" >/dev/null 2>&1
uv pip install --quiet --python "$VERIFY_VENV" --find-links "$DIST" --no-cache curator-mcp

if [ -x "$VERIFY_VENV/bin/python" ]; then
  VERIFY_PY="$VERIFY_VENV/bin/python"
else
  VERIFY_PY="$VERIFY_VENV/Scripts/python.exe"   # Windows layout
fi

"$VERIFY_PY" - <<'CHECK'
import asyncio
from curator_mcp.server import build_server
tools = sorted(t.name for t in asyncio.run(build_server().list_tools()))
expected = ["compare_protocols", "get_market_yields", "get_token_price", "list_markets"]
assert tools == expected, f"expected {expected}, got {tools}"
print("    OK - installed from wheels alone, all four tools resolve")
CHECK
echo

# ── 3. upload ────────────────────────────────────────────────────────────
if [ "$PUBLISH" -eq 0 ]; then
  echo "==> Dry run complete. Nothing uploaded."
  echo "    Artifacts in dist/. Re-run with --publish to upload."
  exit 0
fi

if [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
  if [ -f "$REPO_ROOT/.env" ]; then
    # shellcheck disable=SC2046
    UV_PUBLISH_TOKEN=$(grep -E '^UV_PUBLISH_TOKEN=' "$REPO_ROOT/.env" | head -1 | cut -d= -f2- || true)
    export UV_PUBLISH_TOKEN
  fi
fi

if [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
  echo "ERROR: UV_PUBLISH_TOKEN is not set." >&2
  echo "  Create one at https://pypi.org/manage/account/token/ and either" >&2
  echo "  export it or add UV_PUBLISH_TOKEN=pypi-... to .env" >&2
  exit 1
fi

# curator-schema belongs to Wave 0, not Lane C. It is the bottom of the chain
# so it cannot be skipped, but whoever runs this should know they are
# publishing another lane's package.
echo "==> Uploading. curator-schema is Wave 0's package - publishing it too."
echo "    A version number on PyPI is permanent and cannot be re-uploaded."
if [ "$ASSUME_YES" -eq 1 ]; then
  echo "    --yes given; proceeding."
else
  printf "    Continue? [y/N] "
  read -r reply
  case "$reply" in
    y|Y) ;;
    *) echo "    Aborted."; exit 1 ;;
  esac
fi

for pkg in curator_schema curator_data curator_mcp; do
  echo "==> Publishing $pkg"
  if [ -n "$INDEX" ]; then
    uv publish --publish-url "$INDEX" --token "$UV_PUBLISH_TOKEN" "$DIST/$pkg"-*
  else
    uv publish --token "$UV_PUBLISH_TOKEN" "$DIST/$pkg"-*
  fi
done

echo
echo "==> Done. Confirm the claim SKILL.md makes:"
echo "      uvx curator-mcp        # from a machine that has never seen this repo"
