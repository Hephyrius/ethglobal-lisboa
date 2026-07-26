#!/usr/bin/env bash
# Every `path#Lnn` link in the README points at a line that still means what the
# README says it does.
#
# WHY THIS IS A SCRIPT AND NOT A HABIT
#
# Uniswap's Track 1 requirements say, in their own words, to "make sure your
# README clearly points to the relevant contracts and lines of code". That makes
# a drifted anchor a scored defect, not a cosmetic one — and anchors drift from
# edits made in a different file by a different lane, so nobody who breaks one is
# looking at the README at the time.
#
# It has already happened twice. Two `client.py` anchors slipped by one line when
# an unrelated `LoopBoundClient` refactor landed. Then Wave 3 added `pause()` and
# `redeemInKind()` to CuratedVault.sol and moved all four contract anchors by
# 60-100 lines: `execute` pointed at a revert inside a loop, `holdings()` pointed
# at a blank line.
#
# A line number cannot be checked on its own — it is always *a* line. So each
# anchor is paired below with a regex the target line must match, which is what
# turns "the link resolves" into "the link resolves to the thing described".
#
# POSIX bash 3.2 (macOS ships it), no arrays, no jq. Exits non-zero so it can
# gate a commit or a submission.

set -eu

cd "$(cd "$(dirname "$0")" && pwd)/.."

failures=0

# path | line | regex the line must match
CHECKS="
venues/aqua/calldata.py|56|def ship_step
venues/aqua/calldata.py|89|def dock_step
venues/aqua/venue.py|80|async def plan
venues/uniswap/client.py|155|async def quote
venues/uniswap/client.py|160|async def swap
contracts/src/CuratedVault.sol|158|function execute(
contracts/src/CuratedVault.sol|169|function executeBatch(
contracts/src/CuratedVault.sol|221|function pause(
contracts/src/CuratedVault.sol|228|function unpause(
contracts/src/CuratedVault.sol|239|function redeemInKind(
contracts/src/CuratedVault.sol|289|function totalAssets(
contracts/src/CuratedVault.sol|408|function holdings(
"

echo "README line anchors"

echo "$CHECKS" | while IFS='|' read -r file line pattern; do
  [ -z "$file" ] && continue

  if ! grep -q "($file#L$line)" README.md; then
    printf "  \033[31m✗\033[0m README has no link to %s#L%s — this check is now stale\n" "$file" "$line"
    echo "STALE" >> .anchor-failures
    continue
  fi

  actual="$(sed -n "${line}p" "$file")"
  case "$actual" in
    *"$pattern"*)
      printf "  \033[32m✓\033[0m %s:%s\n" "$file" "$line"
      ;;
    *)
      printf "  \033[31m✗\033[0m %s:%s should be '%s' but is:\n      %s\n" \
        "$file" "$line" "$pattern" "$actual"
      # The right line number, so fixing it is a copy-paste rather than a hunt.
      found="$(grep -n "$pattern" "$file" | head -1 | cut -d: -f1 || true)"
      [ -n "$found" ] && printf "      it moved to line %s\n" "$found"
      echo "MOVED" >> .anchor-failures
      ;;
  esac
done

# The loop above runs in a subshell (it is the right-hand side of a pipe), so a
# counter incremented inside it is lost at the pipe's end — the classic way a
# shell gate reports success while having found failures. A file survives the
# subshell; a variable does not.
if [ -f .anchor-failures ]; then
  failures="$(wc -l < .anchor-failures | tr -d ' ')"
  rm -f .anchor-failures
  echo
  echo "$failures README anchor(s) point somewhere else. Fix README.md before submitting." >&2
  exit 1
fi

echo
echo "All README anchors resolve."
