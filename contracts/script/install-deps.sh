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

# dest | repo | tag | paths to keep | paths to prune after copying
#
# Destination names are deliberately short, and the unused OpenZeppelin trees are deliberately
# pruned. Both exist for the same reason: a fresh `git clone` on Windows aborts when any path exceeds
# the 260-character MAX_PATH, and `lib/openzeppelin-contracts-upgradeable/contracts/mocks/docs/
# access-control/…Upgradeable.sol` came to 130 characters before the clone directory is even counted.
# Nothing here compiles governance, mocks or account abstraction, so dropping them costs nothing and
# roughly halves what a judge has to scroll past.
DEPS=(
  "oz|https://github.com/OpenZeppelin/openzeppelin-contracts|v5.1.0|contracts LICENSE|contracts/mocks contracts/governance contracts/finance contracts/metatx contracts/crosschain contracts/account contracts/vendor"
  "oz-upgradeable|https://github.com/OpenZeppelin/openzeppelin-contracts-upgradeable|v5.1.0|contracts LICENSE|contracts/mocks contracts/governance contracts/finance contracts/metatx contracts/crosschain contracts/account contracts/vendor"
  "forge-std|https://github.com/foundry-rs/forge-std|v1.9.4|src LICENSE-MIT LICENSE-APACHE|"
)

mkdir -p lib

for entry in "${DEPS[@]}"; do
  IFS='|' read -r name repo tag keep prune <<< "$entry"
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

  # Drop trees nothing in src/ or test/ imports. Verified by `forge clean && forge build` — if a
  # prune ever removes something load-bearing, the build fails loudly rather than at deploy time.
  for path in $prune; do
    rm -rf "${dest:?}/${path}"
  done

  echo "$tag" > "$stamp"
  echo "✓ $name $tag"
done

echo
echo "Vendored into contracts/lib/. Remappings in remappings.txt."
