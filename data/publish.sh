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
INCLUDE_SCHEMA=0

for arg in "$@"; do
  case "$arg" in
    --publish)        PUBLISH=1 ;;
    --test-pypi)      INDEX="https://test.pypi.org/legacy/" ;;
    --yes)            ASSUME_YES=1 ;;   # non-interactive; the caller has confirmed
    --include-schema) INCLUDE_SCHEMA=1 ;;
    -h|--help)   sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

# ── 1. build ─────────────────────────────────────────────────────────────
#
# `curator-schema` is LANE F's package and it is deliberately NOT built or
# published by default. Two reasons, both learned rather than assumed:
#
#   1. Releasing another lane's in-flight work is not ours to do. Mid-wave the
#      repo's schema version is routinely ahead of what its owner has decided
#      to publish, and taking that decision for them is how a version number -
#      which is permanent - gets spent on a state nobody signed off.
#   2. It makes the verification below STRONGER. With no schema wheel in dist/,
#      `--find-links` has to resolve `curator-schema` from PyPI, so this run
#      proves our floor is satisfiable by what is actually served. That is the
#      exact blind spot that shipped a broken 0.3.0: building every sibling
#      locally hid a stale published version behind a fresh local wheel.
#
# Pass --include-schema when the floor genuinely cannot be met from the index
# (the check below says so explicitly), and only with its owner's agreement.
echo "==> Building distributions into dist/"
rm -rf "$DIST"
if [ "$INCLUDE_SCHEMA" -eq 1 ]; then
  echo "    --include-schema given: building Lane F's curator-schema too"
  uv build --out-dir "$DIST" packages/schema/python
else
  echo "    (skipping curator-schema - Lane F's package; it will resolve from PyPI)"
fi
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
# `--find-links` alone is NOT enough, and this is the flaw that shipped a
# broken 0.3.0. It resolves every dependency from the freshly built dist,
# including packages this release is NOT publishing - so a sibling whose
# CONTENT changed without a VERSION bump looks fine here and is wrong on PyPI,
# where the old bytes still sit under that version number. Resolving against
# the real index as well surfaces the mismatch before the upload.
if ! uv pip install --quiet --python "$VERIFY_VENV" --find-links "$DIST" --no-cache curator-mcp; then
  echo "    FAILED to resolve." >&2
  if [ "$INCLUDE_SCHEMA" -eq 0 ]; then
    echo "    The likeliest cause is that curator-data's floor on curator-schema" >&2
    echo "    cannot be met by any version PyPI serves. Ask Lane F to release the" >&2
    echo "    schema, or re-run with --include-schema once they agree." >&2
  fi
  exit 1
fi

echo "==> Cross-checking against what PyPI actually serves"
CROSS_VENV=$(mktemp -d)/venv
uv venv --python 3.10 "$CROSS_VENV" >/dev/null 2>&1
if uv pip install --quiet --python "$CROSS_VENV" --no-cache curator-mcp >/dev/null 2>&1; then
  if [ -x "$CROSS_VENV/bin/python" ]; then CROSS_PY="$CROSS_VENV/bin/python"
  else CROSS_PY="$CROSS_VENV/Scripts/python.exe"; fi
  if "$CROSS_PY" -c "import curator_data, curator_mcp.server" >/dev/null 2>&1; then
    echo "    OK - the currently published stack still imports"
  else
    echo "    WARNING: the PUBLISHED stack does not import." >&2
    echo "    A sibling package's content changed without its version being bumped," >&2
    echo "    so PyPI serves stale bytes under a version number we reuse locally." >&2
    echo "    Bump and publish the changed dependency FIRST." >&2
  fi
else
  echo "    (nothing published yet, or PyPI unreachable - skipping cross-check)"
fi

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

echo "==> Uploading."
if [ "$INCLUDE_SCHEMA" -eq 1 ]; then
  echo "    WARNING: --include-schema means you are releasing LANE F's package."
fi
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

# Skip a package whose version is already on PyPI rather than failing on it.
#
# This is the NORMAL case, not an edge case: `curator-schema` belongs to another
# lane and rarely changes, so a release of `curator-data` alone would otherwise
# abort on the first upload and never reach the packages that did change. A
# release script has to be idempotent or it can only ever be run once.
already_published() {
  uv run python - "$1" "$2" <<'CHECK'
import sys, urllib.request
name, version = sys.argv[1].replace("_", "-"), sys.argv[2]
try:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=15) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
CHECK
}

# Bottom of the dependency chain first. Packages not built (see §1) are simply
# not in dist/ and are skipped by the guard below rather than by a second list.
for pkg in curator_schema curator_data curator_mcp; do
  ls "$DIST/$pkg"-*.tar.gz >/dev/null 2>&1 || continue
  version=$(ls "$DIST/$pkg"-*.tar.gz | sed -E "s/.*${pkg}-(.*)\.tar\.gz/\1/" | head -1)
  if already_published "$pkg" "$version"; then
    echo "==> $pkg $version is already on PyPI - skipping (unchanged since last release)"
    continue
  fi
  echo "==> Publishing $pkg $version"
  if [ -n "$INDEX" ]; then
    uv publish --publish-url "$INDEX" --token "$UV_PUBLISH_TOKEN" "$DIST/$pkg"-*
  else
    uv publish --token "$UV_PUBLISH_TOKEN" "$DIST/$pkg"-*
  fi
done

echo
echo "==> Done. Confirm the claim SKILL.md makes:"
echo "      uvx curator-mcp        # from a machine that has never seen this repo"
