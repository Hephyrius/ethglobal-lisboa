#!/usr/bin/env bash
#
# Widen the asset universe every NEW vault is born with.
#
# The agent could hold exactly two assets, USDC and WETH, which made "diversified curation" a claim
# rather than a capability. This registers cbBTC, DAI and AERO as factory-default valuations, and
# their token contracts plus the Aave v3 Pool as factory-default execute() targets.
#
# ── Why this is a script and not a contract change ────────────────────────────────────────────────
#
# VaultFactory.setDefaultValuation(token, feed) and setDefaultTarget(target, bool) are onlyOwner, and
# CuratedVault.initialize() snapshots the factory defaults. So widening the universe is a transaction,
# not a redeploy.
#
# ── The consequence you must know before running this ─────────────────────────────────────────────
#
# **Per-vault valuations are IMMUTABLE and this does not change existing vaults.** That immutability
# is deliberate and correct — VaultFactory's own header argues it: whoever can register a valuation
# can register a bogus feed and mint shares against it. So the wider universe applies only to vaults
# created AFTER this runs. Existing vaults keep the universe they were born with, and the demo should
# create a fresh vault to show the wide one. That is arguably a feature: the genesis conversation is
# where a depositor picks what their curator may touch.
#
# ── Every address here was verified live, not recalled ────────────────────────────────────────────
#
# Tokens: symbol() and decimals() read off the contract on the fork.
# Feeds:  description() read off the aggregator; a wrong feed does not error, it returns a confident
#         and completely wrong price, and the vault mints shares against it.
# aTokens: confirmed TWO ways — UNDERLYING_ASSET_ADDRESS() and Pool.getReserveData(asset)[8].
#
# wstETH is deliberately excluded: its Base feed reports WSTETH/ETH at 18 decimals, not USD, and
# totalAssets() assumes a USD-quoted feed.
#
# ── ERC-4626 share tokens need a feed that does not exist yet ──────────────────────────────────────
#
# A MetaMorpho share is not an aToken. It APPRECIATES rather than rebasing 1:1, so the underlying's
# Chainlink feed is wrong for it — valuing gtUSDCp as plain USDC understates the position by ~760 bps
# and worsens every block (cross-lane request #66). There is also no Chainlink feed for a MetaMorpho
# share and there never will be.
#
# So the feed is composed: ERC4626PriceFeed(vault, assetFeed) answers
# `convertToAssets(1 share) x underlying USD price` behind IAggregatorV3, which is all
# `priceFeed(token)` requires. Lane D wrote it; this script deploys and registers it.
#
# It is DEPLOYED ON DEMAND rather than pasted in as a constant, and that is the whole reason this is
# more than three lines. A deployed helper lives in anvil's state, so a fork restart destroys it and
# a hardcoded address becomes an address with no code — which this script's own verification would
# then reject, correctly but confusingly, in the middle of demo prep. Instead the feed is looked up
# from the factory's own `defaultValuations()` and redeployed only when it is genuinely absent, so
# re-running after an anvil restart repairs the universe instead of failing it.
#
# Usage:
#   ./scripts/expand-universe.sh                  # register everything below
#   ./scripts/expand-universe.sh --dry-run        # print what would be sent
#   ./scripts/expand-universe.sh --rpc http://127.0.0.1:8540
#
# Idempotent: setDefaultValuation and setDefaultTarget both overwrite rather than append, so
# re-running is a no-op. Exits non-zero if the fork is unreachable or the caller does not own the
# factory, so it works as a gate.
#
# Needs `cast` (Foundry). On Windows run it inside `wsl -d Ubuntu-24.04`, like every other Foundry
# script here. POSIX-friendly bash: no arrays, no jq — runs under the bash 3.2 macOS ships.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
# .env is a default; an exported variable is an instruction (#45).
. "$SCRIPT_DIR/lib/load-env.sh"
load_dotenv

RPC="${ANVIL_RPC_URL:-http://127.0.0.1:8540}"
# Which deployment manifest. `DEPLOYMENTS_FILE` is an exact path; otherwise the
# network name Deploy.s.sol writes with, so reader and writer cannot disagree.
NETWORK="${DEPLOY_NETWORK:-base-fork}"
DEPLOYMENTS="${DEPLOYMENTS_FILE:-deployments/${NETWORK}.json}"
DRY_RUN=0

# anvil account 0 — the deployer, and therefore the factory owner on a fork deploy.
OWNER_KEY="${FACTORY_OWNER_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"

while [ $# -gt 0 ]; do
  case "$1" in
    --rpc)     RPC="$2"; shift 2 ;;
    --key)     OWNER_KEY="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v cast >/dev/null 2>&1 || {
  echo "cast not found. Windows: are you in 'wsl -d Ubuntu-24.04'? See CLAUDE.md." >&2
  exit 1
}

[ -f "$DEPLOYMENTS" ] || {
  echo "$DEPLOYMENTS missing — deploy first:" >&2
  echo "  cd contracts && forge script script/Deploy.s.sol --rpc-url $RPC --broadcast" >&2
  exit 1
}

FACTORY="$(sed -n 's/.*"VaultFactory"[[:space:]]*:[[:space:]]*"\(0x[0-9a-fA-F]\{40\}\)".*/\1/p' \
  "$DEPLOYMENTS" | head -1)"
[ -n "$FACTORY" ] || { echo "no VaultFactory address in $DEPLOYMENTS" >&2; exit 1; }

echo "Factory $FACTORY on $RPC"
echo

# ── what to register ──────────────────────────────────────────────────────────────────────────────
#
# "SYMBOL TOKEN FEED" per line. A valuation needs both; a target needs only the address.
# No arrays: a heredoc read line by line is the bash-3.2-safe way to carry a table.

VALUATIONS=$(cat <<'TABLE'
cbBTC    0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf 0x07DA0E54543a844a80ABE69c8A12F22B3aA59f9D
DAI      0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb 0x591e79239a7d679378eC8c847e5038150364C78F
AERO     0x940181a94A35A4569E4529A3CDfB74e38FD98631 0x4EC5970fC728C5f65ba413992CD5fF6FD70fcfF0
aBasUSDC 0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB 0x7e860098F58bBFC8648a4311b374B1D669a2bc6B
aBasWETH 0xD4a0e0b9149BCee3C920d2E00b5dE09138fd8bb7 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70
TABLE
)

# The two aTokens above are why lending works at all. Supply USDC to Aave and the vault receives
# aBasUSDC, which totalAssets() would not count — so the share price would COLLAPSE the moment the
# agent first earned yield. An aToken is a 1:1 rebasing claim on its underlying, so it is correctly
# valued by the underlying's own Chainlink feed. No new contract, no pegged-oracle shim.
#
# Known artefact, documented rather than hidden: raw USDC counts at par inside totalAssets() while
# aBasUSDC is valued through the USDC/USD feed at 0.9999, a constant ~1 bp haircut on the supplied
# portion. On a pinned fork the feed is frozen, so it is an offset and not false volatility.

TARGETS=$(cat <<'TABLE'
cbBTC          0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf
DAI            0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb
AERO           0x940181a94A35A4569E4529A3CDfB74e38FD98631
AaveV3Pool     0xA238Dd80C259a72e81d7e4664a9801593F98d1c5
aBasUSDC       0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB
aBasWETH       0xD4a0e0b9149BCee3C920d2E00b5dE09138fd8bb7
TABLE
)

# Tokens are targets because an approval step targets the TOKEN, not the venue — cross-lane request
# #8, already settled for USDC and WETH. Without this every first swap in a new asset reverts on
# step 1 with TargetNotAllowed, which reads as a venue bug and is not one.

# ── ERC-4626 share tokens ─────────────────────────────────────────────────────────────────────────
#
# "SYMBOL VAULT UNDERLYING_FEED DESCRIPTION…" per line; the description is the rest of the line.
# UNDERLYING_FEED prices the vault's `asset()`, not the share — the share price is composed from it.
#
# Gauntlet USDC Prime is the default of the two verified MetaMorpho vaults on Base ($426M vs $9.3M
# for Moonwell Flagship): a curator supplying into the deeper book is the less interesting claim to
# have to defend. Moonwell Flagship 0xc1256Ae5FF1cf2719D4937adb3bbCCab2E00A2Ca is the alternative.

ERC4626_VALUATIONS=$(cat <<'TABLE'
gtUSDCp 0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61 0x7e860098F58bBFC8648a4311b374B1D669a2bc6B gtUSDCp / USD
TABLE
)

FEED_PROJECT="venues/aqua/solidity"
FEED_CONTRACT="src/ERC4626PriceFeed.sol:ERC4626PriceFeed"

send() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    would send: $*"
    return 0
  fi
  cast send "$FACTORY" "$@" --private-key "$OWNER_KEY" --rpc-url "$RPC" >/dev/null
}

# ── preflight: the node, the factory, and the caller's ownership ──────────────────────────────────

cast chain-id --rpc-url "$RPC" >/dev/null 2>&1 || {
  echo "no node at $RPC — start it with ./scripts/anvil-fork.sh (inside wsl -d Ubuntu-24.04)" >&2
  exit 1
}

CALLER="$(cast wallet address --private-key "$OWNER_KEY")"
FACTORY_OWNER="$(cast call "$FACTORY" "owner()(address)" --rpc-url "$RPC" 2>/dev/null || echo "")"
if [ -n "$FACTORY_OWNER" ] && [ "$(echo "$CALLER" | tr 'A-Z' 'a-z')" != "$(echo "$FACTORY_OWNER" | tr 'A-Z' 'a-z')" ]; then
  echo "caller $CALLER does not own factory $FACTORY (owner is $FACTORY_OWNER)" >&2
  echo "  pass the owner's key with --key, or set FACTORY_OWNER_KEY" >&2
  exit 1
fi

# ── resolve the ERC-4626 share feeds: reuse what is registered, deploy what is missing ────────────
#
# Reuse is decided by asking the CHAIN, not by remembering: `defaultValuations()` already carries
# every (token, feed) pair the factory will hand a new vault, so it is the authority on whether a
# feed exists. That keeps this idempotent with no extra state file to go stale, and makes a re-run
# after an anvil restart a repair rather than a failure.

# The feed a previous run registered for $1, or empty. Output shape is
# `[(0xtoken, 0xfeed), (…)]`, so flatten and pair it up.
registered_feed_for() {
  cast call "$FACTORY" "defaultValuations()((address,address)[])" --rpc-url "$RPC" 2>/dev/null \
    | tr -d '[]() ' | tr ',' '\n' | grep '^0x' \
    | awk -v want="$(echo "$1" | tr 'A-Z' 'a-z')" '
        { if (NR % 2 == 1) { tok = tolower($1) } else if (tok == want) { print $1; exit } }'
}

ERC4626_RESOLVED=""

echo "Resolving ERC-4626 share feeds…"
while read -r SYMBOL VAULT_TOKEN ASSET_FEED FEED_DESC; do
  [ -n "${SYMBOL:-}" ] || continue

  # The share token first. `asset()` is what makes it a 4626 rather than a plain ERC-20, and a
  # missing answer here means the address is wrong — cheaper to learn now than after a deploy.
  UNDERLYING="$(cast call "$VAULT_TOKEN" "asset()(address)" --rpc-url "$RPC" 2>/dev/null || echo "")"
  [ -n "$UNDERLYING" ] || {
    echo "  x $SYMBOL — no asset() at $VAULT_TOKEN; not an ERC-4626 vault" >&2
    exit 1
  }
  SHARE_VALUE="$(cast call "$VAULT_TOKEN" "convertToAssets(uint256)(uint256)" 1000000000000000000 \
    --rpc-url "$RPC" 2>/dev/null | sed 's/[^0-9].*//')"
  echo "  $SYMBOL: 1 share = $SHARE_VALUE of $UNDERLYING (base units)"

  EXISTING="$(registered_feed_for "$VAULT_TOKEN")"
  FEED=""
  if [ -n "$EXISTING" ]; then
    # Registered is not the same as alive: anvil may have restarted since, leaving the address
    # bare. A feed with no code answers nothing, so ask it.
    EXISTING_DESC="$(cast call "$EXISTING" "description()(string)" --rpc-url "$RPC" 2>/dev/null | tr -d '"' || echo "")"
    if [ "$EXISTING_DESC" = "$FEED_DESC" ]; then
      echo "    reusing registered feed $EXISTING ('$EXISTING_DESC')"
      FEED="$EXISTING"
    else
      echo "    registered feed $EXISTING answers '$EXISTING_DESC', expected '$FEED_DESC' — redeploying"
    fi
  fi

  if [ -z "$FEED" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      # Deliberately NOT folded into VALUATIONS: there is no feed address to verify, and a
      # placeholder would fail the verification gate below and report a dry run as broken.
      echo "    would deploy ERC4626PriceFeed($VAULT_TOKEN, $ASSET_FEED, \"$FEED_DESC\")"
      echo "    would then register it as the valuation and an execute() target for $SYMBOL"
      continue
    fi
    command -v forge >/dev/null 2>&1 || {
      echo "  x forge not found, and $SYMBOL needs a feed deployed." >&2
      echo "    Windows: run inside 'wsl -d Ubuntu-24.04' with ~/.foundry/bin on PATH." >&2
      exit 1
    }
    echo "    deploying ERC4626PriceFeed($VAULT_TOKEN, $ASSET_FEED, \"$FEED_DESC\")…"
    # `--constructor-args` MUST come last. It is variadic, so anything after it is swallowed as
    # another constructor argument — put `--rpc-url` behind it and forge silently deploys to its
    # default `localhost:8545` instead, which fails with a connection error naming a port you
    # never asked for. Cost twenty minutes; leaving the note so it costs nobody else any.
    DEPLOY_LOG="$(cd "$FEED_PROJECT" && forge create "$FEED_CONTRACT" \
      --private-key "$OWNER_KEY" --rpc-url "$RPC" --broadcast \
      --constructor-args "$VAULT_TOKEN" "$ASSET_FEED" "$FEED_DESC" 2>&1)" || true
    FEED="$(printf '%s\n' "$DEPLOY_LOG" | sed -n 's/^Deployed to: \(0x[0-9a-fA-F]\{40\}\).*/\1/p')"
    [ -n "$FEED" ] || {
      echo "  x deploy produced no address for $SYMBOL. forge said:" >&2
      printf '%s\n' "$DEPLOY_LOG" | sed 's/^/      /' >&2
      exit 1
    }
    echo "    deployed at $FEED"
  fi

  # ── the check description() cannot make ──────────────────────────────────────────────────────
  #
  # Lane D flagged this: ETH/USD and USDC/USD are both 8-decimal aggregators, so a feed built
  # against the WRONG underlying still describes itself correctly and still answers confidently.
  # The magnitude is what gives it away. Compose the expected answer independently —
  # convertToAssets(1 share) x the underlying's own answer — and require the deployed feed to
  # agree within 1%. Wrong-underlying is off by ~1,700x here, not by 1%.
  ASSET_ANSWER="$(cast call "$ASSET_FEED" "latestRoundData()(uint80,int256,uint256,uint256,uint80)" \
    --rpc-url "$RPC" 2>/dev/null | sed -n 2p | sed 's/[^0-9].*//')"
  FEED_ANSWER="$(cast call "$FEED" "latestRoundData()(uint80,int256,uint256,uint256,uint80)" \
    --rpc-url "$RPC" 2>/dev/null | sed -n 2p | sed 's/[^0-9].*//')"
  UNDERLYING_UNIT="$(cast call "$UNDERLYING" "decimals()(uint8)" --rpc-url "$RPC" 2>/dev/null | sed 's/[^0-9].*//')"
  if [ -n "$ASSET_ANSWER" ] && [ -n "$FEED_ANSWER" ] && [ -n "$SHARE_VALUE" ] && [ -n "$UNDERLYING_UNIT" ]; then
    SCALE=1; i=0
    while [ "$i" -lt "$UNDERLYING_UNIT" ]; do SCALE=$((SCALE * 10)); i=$((i + 1)); done
    EXPECTED=$(( SHARE_VALUE * ASSET_ANSWER / SCALE ))
    DIFF=$(( FEED_ANSWER - EXPECTED )); [ "$DIFF" -ge 0 ] || DIFF=$(( -DIFF ))
    if [ "$EXPECTED" -gt 0 ] && [ $(( DIFF * 100 )) -gt "$EXPECTED" ]; then
      echo "  x $SYMBOL feed answers $FEED_ANSWER, composed expectation is $EXPECTED — >1% apart." >&2
      echo "    That is the signature of a feed built against the wrong underlying: it would" >&2
      echo "    describe itself correctly and price the position confidently wrong." >&2
      exit 1
    fi
    echo "    answers $FEED_ANSWER against a composed expectation of $EXPECTED — agrees"
  else
    echo "    ! could not compose an independent expectation; registering on description() alone" >&2
  fi

  ERC4626_RESOLVED="$ERC4626_RESOLVED
$SYMBOL $VAULT_TOKEN $FEED"
done <<TABLE_END
$ERC4626_VALUATIONS
TABLE_END

# Fold them into the normal tables so they go through the same verification and the same
# registration path as everything else — a 4626 share is not a special case downstream.
VALUATIONS="$VALUATIONS$ERC4626_RESOLVED"
while read -r SYMBOL VAULT_TOKEN FEED; do
  [ -n "${SYMBOL:-}" ] || continue
  TARGETS="$TARGETS
$SYMBOL $VAULT_TOKEN"
done <<TABLE_END
$ERC4626_RESOLVED
TABLE_END

echo

# ── verify every address before trusting it ───────────────────────────────────────────────────────
#
# Not paranoia. A wrong token address makes the vault value a balance it does not hold; a wrong feed
# address returns a well-formed, confident, completely wrong price and mints shares against it.
# Checking costs one eth_call each and turns a silent demo-time failure into a startup error.

echo "Verifying addresses on-chain…"
FAILED=0
# Fed by redirection, NOT `echo … | while`. A pipeline puts the loop in a subshell, so FAILED would be
# discarded the moment the loop ends and a failed verification would silently proceed to send
# transactions. The first version of this ran the whole loop twice to work around that, which doubled
# the slowest part of the script — an uncached `cast call` against a fork is forwarded upstream and
# takes seconds, so ten of them is most of the runtime.
while read -r SYMBOL TOKEN FEED; do
  [ -n "${SYMBOL:-}" ] || continue
  ONCHAIN_SYMBOL="$(cast call "$TOKEN" "symbol()(string)" --rpc-url "$RPC" 2>/dev/null | tr -d '"' || echo "")"
  DESCRIPTION="$(cast call "$FEED" "description()(string)" --rpc-url "$RPC" 2>/dev/null | tr -d '"' || echo "")"
  if [ -z "$ONCHAIN_SYMBOL" ] || [ -z "$DESCRIPTION" ]; then
    echo "  x $SYMBOL - no code, or not the contract we expect, at $TOKEN / $FEED" >&2
    FAILED=1
  else
    echo "  ok $SYMBOL is '$ONCHAIN_SYMBOL', priced by '$DESCRIPTION'"
  fi
done <<TABLE_END
$VALUATIONS
TABLE_END

[ "$FAILED" -eq 0 ] || {
  echo "refusing to register an unverified address - a wrong feed returns a confident," >&2
  echo "well-formed, completely wrong price, and the vault mints shares against it." >&2
  exit 1
}

echo
echo "Registering default valuations (new vaults only)…"
echo "$VALUATIONS" | while read -r SYMBOL TOKEN FEED; do
  [ -n "${SYMBOL:-}" ] || continue
  echo "  $SYMBOL -> $FEED"
  send "setDefaultValuation(address,address)" "$TOKEN" "$FEED"
done

echo
echo "Registering default execute() targets…"
echo "$TARGETS" | while read -r LABEL ADDRESS; do
  [ -n "${LABEL:-}" ] || continue
  echo "  $LABEL $ADDRESS"
  send "setDefaultTarget(address,bool)" "$ADDRESS" true
done

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run — nothing sent."
  exit 0
fi

# ── republish the manifest ────────────────────────────────────────────────────────────────────────
#
# `deployments/base-fork.json` → `executeAllowlist.targets` is what every lane reads to decide
# whether a plan's target will be accepted, and `Deploy.s.sol` wrote it as a snapshot of the
# factory defaults *at deploy time*. Having just widened those defaults, the file is now stale in a
# way that fails closed but confusingly: `venues` refuses to emit a plan targeting the Aave pool,
# and the error reads as a venue bug rather than as "the manifest predates this change".
#
# So the manifest is rewritten from `defaultTargets()`, which is the authority for what a vault
# created from now on will allow. Existing vaults still allow only what they were born with — that
# gap is real and is why the venue adapters check the aToken explicitly before supplying.
#
# Rewritten with awk rather than jq: jq is not installed on the macOS handoff machine and adding a
# dependency to a script whose whole job is one array would be a poor trade.

TARGETS_RAW="$(cast call "$FACTORY" "defaultTargets()(address[])" --rpc-url "$RPC")"
COUNT="$(echo "$TARGETS_RAW" | tr ',' '\n' | grep -c '0x' || true)"

echo "Republishing executeAllowlist in $DEPLOYMENTS ($COUNT target(s))…"
echo "$TARGETS_RAW" | tr -d '[] ' | tr ',' '\n' | grep '^0x' > "$DEPLOYMENTS.targets.tmp"

awk -v listfile="$DEPLOYMENTS.targets.tmp" '
  /"targets": \[/ {
    print
    n = 0
    while ((getline line < listfile) > 0) { addrs[n++] = line }
    close(listfile)
    for (i = 0; i < n; i++) {
      printf "      \"%s\"%s\n", addrs[i], (i < n - 1 ? "," : "")
    }
    skip = 1
    next
  }
  skip && /\]/ { skip = 0; print; next }
  skip { next }
  { print }
' "$DEPLOYMENTS" > "$DEPLOYMENTS.tmp"

# Only replace the real file once the rewrite has produced something plausible. A truncated
# manifest would take down every lane at once, and a half-written one is worse than a stale one.
if grep -q '"VaultFactory"' "$DEPLOYMENTS.tmp" && grep -q '"executeAllowlist"' "$DEPLOYMENTS.tmp"; then
  mv "$DEPLOYMENTS.tmp" "$DEPLOYMENTS"
  echo "  manifest updated"
else
  echo "  refused to write a manifest missing VaultFactory or executeAllowlist — left as-is" >&2
  rm -f "$DEPLOYMENTS.tmp"
fi
rm -f "$DEPLOYMENTS.targets.tmp"

# ── Publish the asset symbols too ─────────────────────────────────────────────────────────────────
#
# `executeAllowlist.targets` is addresses only, and `external` carries just USDC and WETH from the
# deploy. So everything registered above — cbBTC, DAI, AERO, both aTokens, the 4626 share — existed
# on chain with no symbol recorded anywhere a reader could find it. The dApp's asset-universe panel
# consequently listed two assets out of eight, and looked like the feature had never been built.
# That is the same failure mode this script's own comments describe for the Aave venue: an omission
# is indistinguishable from the thing not existing.
#
# So the symbols this script already knows are written back as `assets`. A dedicated block rather
# than folding into `external`, because everything in `assets` is by definition a token the factory
# can value — no consumer has to guess which entries are tokens and which are routers.

echo "Publishing asset symbols in $DEPLOYMENTS…"

# USDC and WETH come from the deploy, not from this script's tables, so they are read back out of
# `external` rather than assumed. Reading them keeps the block honest if Lane A ever redeploys
# against different addresses.
manifest_addr() {
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\(0x[0-9a-fA-F]\{40\}\)\".*/\1/p" "$DEPLOYMENTS" | head -1
}
BASE_USDC="$(manifest_addr USDC)"
BASE_WETH="$(manifest_addr WETH)"

{
  [ -n "$BASE_USDC" ] && printf 'USDC %s\n' "$BASE_USDC"
  [ -n "$BASE_WETH" ] && printf 'WETH %s\n' "$BASE_WETH"
  echo "$VALUATIONS" | awk 'NF >= 2 { print $1, $2 }'
  echo "$ERC4626_VALUATIONS" | awk 'NF >= 2 { print $1, $2 }'
} | awk 'NF == 2 && !seen[$1]++' > "$DEPLOYMENTS.assets.tmp"

# Replaces any existing `assets` block rather than appending, so re-running stays idempotent.
awk -v listfile="$DEPLOYMENTS.assets.tmp" '
  /^  "assets": \{/ { skip = 1; next }
  skip && /^  \},?$/ { skip = 0; next }
  skip { next }
  /^  "chainId":/ && !done {
    print "  \"assets\": {"
    n = 0
    while ((getline line < listfile) > 0) { rows[n++] = line }
    close(listfile)
    for (i = 0; i < n; i++) {
      split(rows[i], f, " ")
      printf "    \"%s\": \"%s\"%s\n", f[1], f[2], (i < n - 1 ? "," : "")
    }
    print "  },"
    done = 1
  }
  { print }
' "$DEPLOYMENTS" > "$DEPLOYMENTS.tmp2"

if grep -q '"VaultFactory"' "$DEPLOYMENTS.tmp2" && grep -q '"assets"' "$DEPLOYMENTS.tmp2"; then
  mv "$DEPLOYMENTS.tmp2" "$DEPLOYMENTS"
  echo "  $(wc -l < "$DEPLOYMENTS.assets.tmp" | tr -d ' ') asset symbol(s) published"
else
  echo "  refused to write an asset block that lost VaultFactory — left as-is" >&2
  rm -f "$DEPLOYMENTS.tmp2"
fi
rm -f "$DEPLOYMENTS.assets.tmp"

echo
echo "Done. The factory now carries $COUNT default target(s)."
echo "Existing vaults are UNCHANGED by design — create a new vault to use the wider universe."
