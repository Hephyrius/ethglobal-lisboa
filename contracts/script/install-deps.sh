#!/usr/bin/env bash
#
# Vendor this project's Solidity dependencies into contracts/lib/ at pinned tags.
#
# WHY NOT `forge install`: it uses git submodules, which live in the repository-root .gitmodules —
# a shared file that Lane D also writes when it sets up venues/aqua/solidity/, and two agents
# editing it concurrently is exactly the collision INSTRUCTIONS.md Rule 7 exists to prevent. Vendored
# sources also mean a plain `git clone` is enough on macOS at handoff: no `--recursive`, no
# `submodule update --init`, no half-empty lib/ that fails to compile with a confusing error.
#
# The result is committed. Re-running is only needed to change a pinned version.
#
# Usage:
#   ./script/install-deps.sh            # install anything missing or at the wrong version
#   ./script/install-deps.sh --force    # re-fetch everything from scratch
#
# POSIX bash. Runs unchanged in wsl -d Ubuntu-24.04 and on macOS.

set -euo pipefail

cd "$(dirname "$0")/.."

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# name | repo | tag | space-separated paths to keep
DEPS=(
  "openzeppelin-contracts|https://github.com/OpenZeppelin/openzeppelin-contracts|v5.1.0|contracts LICENSE"
  "openzeppelin-contracts-upgradeable|https://github.com/OpenZeppelin/openzeppelin-contracts-upgradeable|v5.1.0|contracts LICENSE"
  "forge-std|https://github.com/foundry-rs/forge-std|v1.9.4|src LICENSE-MIT LICENSE-APACHE"
)

mkdir -p lib

for entry in "${DEPS[@]}"; do
  IFS='|' read -r name repo tag keep <<< "$entry"
  dest="lib/$name"
  stamp="$dest/.vendored-version"

  if [ "$FORCE" -eq 0 ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$tag" ]; then
    echo "✓ $name $tag already vendored"
    continue
  fi

  echo "→ fetching $name $tag"
  rm -rf "$dest" "$dest.tmp"
  git clone --quiet --depth 1 --branch "$tag" "$repo" "$dest.tmp"

  # Strip history and the upstream repo's own .gitignore files — vendored, those would ignore
  # files we are deliberately committing.
  rm -rf "$dest.tmp/.git"
  find "$dest.tmp" -name '.gitignore' -type f -delete
  find "$dest.tmp" -name '.gitmodules' -type f -delete

  # Keep only what the remappings actually resolve into. OpenZeppelin's repo is mostly tests,
  # scripts and node tooling; dragging that in would add megabytes nothing compiles against.
  mkdir -p "$dest"
  for path in $keep; do
    [ -e "$dest.tmp/$path" ] && cp -R "$dest.tmp/$path" "$dest/"
  done
  rm -rf "$dest.tmp"

  echo "$tag" > "$stamp"
  echo "✓ $name $tag"
done

echo
echo "Vendored into contracts/lib/. Remappings in remappings.txt."
