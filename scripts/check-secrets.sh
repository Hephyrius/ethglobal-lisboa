#!/usr/bin/env sh
#
# Refuse to commit or push a credential.
#
# We already paid for this lesson: `env.txt` was committed in 408072f by a `git add -A`, carrying
# eight live credentials including a PyPI publish token for three packages that are now public
# (cross-lane request #53). A history purge was considered and correctly DECLINED — the blob stays
# fetchable on GitHub by its SHA regardless, so rewriting buys hygiene against casual discovery at
# the price of breaking every live clone. **Rotation is the remediation.** This script is the part
# that stops the next one, and `docs/secrets.md` is the part that cleans up after it.
#
# ── Usage ─────────────────────────────────────────────────────────────────────────────────────────
#
#   ./scripts/check-secrets.sh                 # scan STAGED content (the pre-commit / pre-push use)
#   ./scripts/check-secrets.sh --tree          # scan every tracked file in the working tree
#   ./scripts/check-secrets.sh --history       # scan all commits ever (slow; run it once, honestly)
#   ./scripts/check-secrets.sh --history HEAD~20..HEAD
#   ./scripts/check-secrets.sh --install       # install as .git/hooks/pre-commit AND pre-push
#   ./scripts/check-secrets.sh --list-rules    # what it looks for, and why each rule exists
#
# Exit 0 clean · 1 findings · 2 usage error. Findings print `path:line  rule  redacted-snippet`.
#
# ── Two design decisions worth arguing with ───────────────────────────────────────────────────────
#
# **Anvil's keys are allowlisted, on purpose.** `AGENT_PRIVATE_KEY` is anvil account #1 and its key
# is printed in Foundry's own documentation; the same ten keys appear in every fork script here. A
# checker that screams about them trains everyone to pass `--no-verify`, and a check that is routinely
# bypassed protects nothing. Being loud about the public keys is how you become quiet about the real
# ones.
#
# **Compiled artifacts and lockfiles are skipped.** `venues/aqua/program_builder.json` is committed
# deployed bytecode: tens of kilobytes of maximum-entropy hex that is not, and can never be, a
# credential. Same for `contracts/out/**`, `contracts/abis/**` and `pnpm-lock.yaml`. Scanning them
# guarantees a wall of false positives, which has exactly one outcome — the check gets disabled.
#
# POSIX `sh`, no arrays, no jq, no python: it has to run on the macOS handoff machine and inside a
# git hook, where PATH is minimal.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

MODE="staged"
RANGE=""
QUIET=0
# Patterns for values that are high-entropy AND public — Graph subgraph IDs and the like. Its
# header carries the rule that keeps it honest.
ALLOW_FILE=""
[ -f "$REPO_ROOT/.secrets-allow" ] && ALLOW_FILE="$REPO_ROOT/.secrets-allow"

while [ $# -gt 0 ]; do
  case "$1" in
    --staged)  MODE="staged"; shift ;;
    --tree)    MODE="tree"; shift ;;
    --history)
      MODE="history"; shift
      case "${1:-}" in -*|"") RANGE="" ;; *) RANGE="$1"; shift ;; esac ;;
    --install) MODE="install"; shift ;;
    --list-rules) MODE="rules"; shift ;;
    --quiet|-q) QUIET=1; shift ;;
    -h|--help) sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# ── paths that never carry a credential and always carry high-entropy noise ───────────────────────

is_skipped_path() {
  case "$1" in
    *contracts/out/*|*contracts/abis/*|*contracts/lib/*|*/node_modules/*|*.lock|*pnpm-lock.yaml|\
    *uv.lock|*program_builder.json|*.png|*.jpg|*.gif|*.woff*|*.ico|*.pdf|*.min.js|*.map|\
    *packages/schema/ts/node_modules/*) return 0 ;;
  esac
  return 1
}

# ── the rules ─────────────────────────────────────────────────────────────────────────────────────
#
# Shape rules first, because a known key shape is a certainty rather than a guess. Entropy last,
# because entropy alone is where false positives live.

if [ "$MODE" = "rules" ]; then
  cat <<'RULES'
Shape rules — a match is a credential, not a guess:

  pypi-token        pypi-AgEI…            can publish new versions of curator-schema,
                                          curator-data and curator-mcp, all live on PyPI. FIRST
                                          in the rotation order for that reason.
  private-key       0x + 64 hex           an EVM private key, unless it is one of anvil's ten
                                          published test keys (allowlisted — see the header).
  github-token      ghp_ gho_ ghu_ ghs_ ghr_ github_pat_
  aws-key           AKIA + 16
  slack-token       xox[baprs]-
  google-key        AIza + 35
  openai-key        sk- + 32 or more      also matches Anthropic-style sk-ant- keys.
  jwt               eyJ…                  three base64url segments. The Graph market JWTs are
                                          this shape, and one is already in history.
  rpc-url-key       alchemy/infura/quicknode/ankr URL with an embedded key
  assignment        KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL = 16+ non-placeholder chars

Entropy rule — a guess, reported so a human can judge:

  high-entropy      a 24+ char base64-ish run with Shannon entropy above 4.5 bits per
                    character. That threshold is measured, not chosen: this repo's identifiers
                    top out at 4.19 and genuinely random strings start at 4.82. Skipped inside
                    compiled artifacts and lockfiles, for pure hex (a hash or calldata is
                    public), for single-case identifiers, and for placeholders.

Suppress a specific line by ending it with:  secrets-check: allow
Doing that is a claim you are making in writing, in a file someone will read.
RULES
  exit 0
fi

# ── hook installation ─────────────────────────────────────────────────────────────────────────────
#
# Both hooks, for different reasons: pre-commit is where a mistake is still cheap to fix, and
# pre-push is the last gate before the blob leaves the machine and becomes permanent.

if [ "$MODE" = "install" ]; then
  HOOK_DIR="$(git rev-parse --git-path hooks)"
  mkdir -p "$HOOK_DIR"
  for HOOK in pre-commit pre-push; do
    cat > "$HOOK_DIR/$HOOK" <<'HOOK_BODY'
#!/usr/bin/env sh
# Installed by scripts/check-secrets.sh --install. Scans staged content only.
exec "$(git rev-parse --show-toplevel)/scripts/check-secrets.sh" --staged
HOOK_BODY
    chmod +x "$HOOK_DIR/$HOOK"
    echo "installed $HOOK_DIR/$HOOK"
  done
  echo
  echo "Both hooks scan STAGED content. A hook is local and unversioned, so it protects this"
  echo "clone only — CI or a habit is what protects the others. Bypass with --no-verify if you"
  echo "must, and say so in the commit message."
  exit 0
fi

# ── the scanner ───────────────────────────────────────────────────────────────────────────────────
#
# One awk program over `path<TAB>lineno<TAB>content` records, so every mode shares exactly one
# implementation of what a secret looks like. Three modes producing three near-identical greps is
# how the rules drift apart.

scan() {
  awk -v skip_entropy="${SKIP_ENTROPY:-0}" -v allowfile="$ALLOW_FILE" -F'\t' '
    function redact(s,   n) {
      n = length(s)
      if (n <= 8) return "…"
      return substr(s, 1, 4) "…" substr(s, n - 1, 2) "  (" n " chars)"
    }
    # Shannon entropy in bits per character. A real key is near-uniform over its alphabet;
    # English prose and hex-with-structure are not.
    function entropy(s,   i, c, n, freq, h, p) {
      n = length(s)
      if (n == 0) return 0
      for (i = 1; i <= n; i++) { c = substr(s, i, 1); freq[c]++ }
      for (c in freq) { p = freq[c] / n; h -= p * log(p) / log(2) }
      return h
    }
    function report(path, line, rule, snippet) {
      # Allowlisted values are counted, never silently dropped. A suppression nobody can see is
      # the same failure as a band nobody can see: it looks like a rule and behaves like none.
      if (allow != "" && snippet ~ allow) { suppressed++; return }
      printf "%s:%s\t%s\t%s\n", path, line, rule, redact(snippet)
      found++
    }

    BEGIN {
      found = 0; suppressed = 0; allow = ""
      if (allowfile != "") {
        while ((getline line < allowfile) > 0) {
          if (line ~ /^[[:space:]]*(#|$)/) continue
          allow = (allow == "" ? line : allow "|" line)
        }
        close(allowfile)
      }
      # anvil accounts 0-9. Published in Foundry docs; deliberately not secrets.
      ANVIL = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80|" \
              "59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d|" \
              "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a|" \
              "7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6|" \
              "47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a|" \
              "8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba|" \
              "92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e|" \
              "4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356|" \
              "dbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97|" \
              "2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6"
      PLACEHOLDER = "your[-_]|changeme|placeholder|redacted|example|xxxxx|<[a-z-]+>|\\.\\.\\.|" \
                    "0xYOUR|INSERT|TODO|dummy|fake|sample"
    }

    { path = $1; lineno = $2; content = $3 }

    content ~ /secrets-check: allow/ { next }

    # ── shape rules ─────────────────────────────────────────────────────────────────────────
    {
      if (match(content, /pypi-AgEI[A-Za-z0-9_-]{20,}/)) {
        report(path, lineno, "pypi-token", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /0x[0-9a-fA-F]{64}/)) {
        key = tolower(substr(content, RSTART + 2, 64))
        if (key !~ ("^(" ANVIL ")$")) {
          # A 32-byte hex word is also a tx hash, a keccak hash, a bytes32 and a salt, all of
          # which are public. Only claim "private key" when the line says so.
          if (tolower(content) ~ /private[-_ ]?key|privkey|secret|mnemonic|\bsk\b/) {
            report(path, lineno, "private-key", substr(content, RSTART, RLENGTH)); next
          }
        }
      }
      if (match(content, /(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}/)) {
        report(path, lineno, "github-token", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /AKIA[0-9A-Z]{16}/)) {
        report(path, lineno, "aws-key", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /xox[baprs]-[A-Za-z0-9-]{10,}/)) {
        report(path, lineno, "slack-token", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /AIza[0-9A-Za-z_-]{35}/)) {
        report(path, lineno, "google-key", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /sk-[A-Za-z0-9_-]{32,}/)) {
        report(path, lineno, "openai-key", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/)) {
        report(path, lineno, "jwt", substr(content, RSTART, RLENGTH)); next
      }
      if (match(content, /(alchemy|infura|quicknode|ankr)[a-z0-9.\/-]*\/(v2\/)?[A-Za-z0-9_-]{20,}/)) {
        if (content !~ PLACEHOLDER) {
          report(path, lineno, "rpc-url-key", substr(content, RSTART, RLENGTH)); next
        }
      }
      if (match(content, /(API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_?KEY)[A-Z_]*[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_+\/=.-]{16,}/)) {
        hit = substr(content, RSTART, RLENGTH)
        if (hit !~ PLACEHOLDER && content !~ PLACEHOLDER) {
          report(path, lineno, "assignment", hit); next
        }
      }

      # ── entropy rule ──────────────────────────────────────────────────────────────────────
      #
      # The only guess in the file, and the reason the exclusions below are as long as the rule:
      # a first pass over the commit that leaked env.txt found the real credentials AND 18 lines
      # of Python identifiers, which is the ratio that gets a checker deleted. Every exclusion
      # here is a shape that is high-entropy by nature and public by nature.
      if (skip_entropy) next
      rest = content
      # `/` is deliberately NOT in the alphabet, which splits `plans/2026-07-25-master-build-plan`
      # and `venues/aqua/solidity/test/…` into harmless pieces. It costs the ability to see a
      # standard-base64 secret as one token — but a real one is long enough that the segments
      # between its slashes still trip the rule, and the alternative was measured: with `/`
      # included, a full-tree scan of this repo returned 554 findings, every one of them a file
      # path or an identifier in a markdown document. A checker at that signal-to-noise ratio is
      # one someone turns off.
      while (match(rest, /[A-Za-z0-9+_-]{24,}={0,2}/)) {
        tok = substr(rest, RSTART, RLENGTH)
        rest = substr(rest, RSTART + RLENGTH)
        # A flag prefix is not part of the value: `--key -0xac09…` arrives as one token and would
        # otherwise dodge the hex and anvil filters on the strength of a leading dash. Trailing
        # base64 padding carries no signal either.
        gsub(/^[-_]+|[-_=]+$/, "", tok)
        if (tok ~ PLACEHOLDER) continue
        if (tolower(tok) ~ ("(" ANVIL ")")) continue
        # No digit and not very long: this is prose or a CamelCase identifier. Generated
        # credentials draw from an alphabet that includes digits, so a 25-character run of pure
        # letters is `useAccountWithSomething`, not a key. Length 40+ overrides, because a long
        # letters-only run stops being plausible as one word.
        if (tok !~ /[0-9]/ && length(tok) < 40) continue
        # Hex: calldata, a tx hash, a bytes32, an address. High entropy, entirely public. The
        # shape rules above already catch a hex string that is *labelled* a private key.
        if (tok ~ /^(0[xX])?[0-9a-fA-F]+$/) continue
        # Identifiers. `test_the_snapshot_degrades_rather_than_failing` scores 3.7 bits/char and
        # is a function name. Single-case plus underscores is code, not a credential: real tokens
        # mix case or carry +/-.
        if (tok ~ /_/ && (tok ~ /^[a-z0-9_]+$/ || tok ~ /^[A-Z0-9_]+$/)) continue
        # Lowercase kebab/snake runs: dated plan filenames, module paths, slugs.
        if (tok ~ /^[a-z0-9_-]+$/ && tok !~ /[A-Z]/) continue
        # 4.5 bits/char, and the number is measured rather than picked. Across the content of this
        # repository the two populations do not overlap: percentageFee 2.81,
        # testTheVaultRevertsWhenTheFeedIsStale 3.71, 2026-07-25-master-build-plan 4.01,
        # invariantTotalAssetsEqualsSumOfHoldings 4.19 -- then nothing at all until a genuinely
        # random string, a Graph subgraph ID at 4.82. Base64 credentials sit near 5.5. Putting the
        # threshold in that gap dropped ~100 identifier false positives without losing one key.
        if (entropy(tok) > 4.5) report(path, lineno, "high-entropy", tok)
      }
    }

    END {
      # stderr, not stdout: stdout IS the findings list, and a suppression is not a finding.
      # Printing it there once made a clean tree scan report itself as dirty.
      if (suppressed > 0)
        printf "  (%d value(s) allowlisted by .secrets-allow)\n", suppressed > "/dev/stderr"
      if (found > 0) exit 1
    }
  '
}

# ── input collection, one function per mode ───────────────────────────────────────────────────────

emit_staged() {
  # Added lines only. What is already in the file is someone else's problem to rotate; what you
  # are adding right now is the thing still worth stopping.
  git diff --cached --unified=0 --no-color --diff-filter=ACMR | awk '
    /^\+\+\+ b\// { path = substr($0, 7); next }
    /^@@/ {
      # @@ -a,b +c,d @@ — c is the first new line number.
      match($0, /\+[0-9]+/); lineno = substr($0, RSTART + 1, RLENGTH - 1) + 0; next
    }
    /^\+/ && path != "" {
      printf "%s\t%s\t%s\n", path, lineno, substr($0, 2)
      lineno++
    }
  '
}

emit_tree() {
  git ls-files -z | while IFS= read -r -d '' FILE; do
    is_skipped_path "$FILE" && continue
    [ -f "$FILE" ] || continue
    awk -v path="$FILE" '{ printf "%s\t%s\t%s\n", path, NR, $0 }' "$FILE" 2>/dev/null || true
  done
}

emit_history() {
  # Every added line in every commit in range. Paths keep their commit so a finding can be
  # traced; line numbers are meaningless across a rewrite, so the commit stands in for one.
  # shellcheck disable=SC2086
  git log --no-color --format='COMMIT %h' -p ${RANGE:-} | awk '
    /^COMMIT / { commit = $2; next }
    /^\+\+\+ b\// { path = substr($0, 7); next }
    /^\+/ && path != "" && $0 !~ /^\+\+\+/ {
      printf "%s@%s\t-\t%s\n", path, commit, substr($0, 2)
    }
  '
}

# `git ls-files -z | read -d ''` needs bash; fall back where sh is not bash.
if [ "$MODE" = "tree" ] && [ -z "${BASH_VERSION:-}" ]; then
  emit_tree() {
    git ls-files | while IFS= read -r FILE; do
      is_skipped_path "$FILE" && continue
      [ -f "$FILE" ] || continue
      awk -v path="$FILE" '{ printf "%s\t%s\t%s\n", path, NR, $0 }' "$FILE" 2>/dev/null || true
    done
  }
fi

case "$MODE" in
  staged)  LABEL="staged content"; INPUT=emit_staged ;;
  tree)    LABEL="every tracked file"; INPUT=emit_tree ;;
  history) LABEL="history ${RANGE:-(all commits)}"; INPUT=emit_history ;;
  *)       echo "unreachable mode $MODE" >&2; exit 2 ;;
esac

[ "$QUIET" -eq 1 ] || echo "Scanning $LABEL for credentials…"

FINDINGS="$("$INPUT" | scan)" && RC=0 || RC=$?

if [ -z "$FINDINGS" ]; then
  [ "$QUIET" -eq 1 ] || echo "clean."
  exit 0
fi

echo
echo "$FINDINGS" | sed 's/^/  /'
echo
COUNT="$(printf '%s\n' "$FINDINGS" | grep -c . || true)"
echo "$COUNT finding(s). Snippets are redacted — the real value is in the file, not here."
echo
cat <<'ADVICE'
If any of these is real, ROTATION IS THE REMEDIATION, not a history rewrite: once a blob has
been pushed it stays fetchable on GitHub by its SHA until GitHub garbage-collects, which needs a
support ticket. Rewriting breaks every live clone and closes nothing. Rotation order and the
current exposure are in docs/secrets.md.

If a finding is a false positive, end the line with `secrets-check: allow` — in a file someone
will read, which is the point.
ADVICE
exit "${RC:-1}"
