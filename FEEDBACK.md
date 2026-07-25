# Uniswap Developer Feedback

Feedback on the **Uniswap Trading API** (`https://trade-api.gateway.uniswap.org/v1`)
from building an autonomous agent that uses it as its execution venue.

**Project:** an ERC-4626 vault curated by an LLM agent. The agent decides
allocation from live market data and executes rotations through the Trading API.
**Integration:** [`venues/uniswap/`](venues/uniswap/) — `client.py` (HTTP),
`plan.py` (response → transaction plan), `venue.py` (adapter).
**Chain:** Base (8453). **Language:** Python, plain HTTP — no SDK.
**Built:** ETHGlobal Lisbon, 25 July 2026.

Written from an integration that reached working `/quote` → `/swap` → executable
calldata in about 40 minutes. Most of that was good. The specific items below
are where we lost time or had to guess.

---

## 1. `routingPreference: CLASSIC` is rejected, but successful responses echo it back

The highest-friction issue we hit, and the first thing we hit.

```
POST /quote  {"routingPreference": "CLASSIC", …}
→ 400  {"errorCode":"RequestValidationError",
        "detail":"\"routingPreference\" must be one of [BEST_PRICE, FASTEST]"}
```

Send `BEST_PRICE` instead and it succeeds — and the response body contains:

```json
{ "routing": "CLASSIC", "quote": { … } }
```

So `CLASSIC` is a valid value of the *response* field `routing` and an invalid
value of the *request* field `routingPreference`. The names are similar enough,
and `CLASSIC` is prominent enough in surrounding material, that trying it first
is a natural move. The error message is genuinely good — it names both valid
values, which is why this cost us minutes rather than an hour — but the
round-trip asymmetry is the kind of thing an integrator assumes is symmetric.

**Suggestion:** either accept `CLASSIC` as an alias for `BEST_PRICE`, or name
the response field something that cannot be mistaken for the request field
(`resolvedRouting`, say). Failing both, an explicit note in the `/quote` docs
that `routing` (response) and `routingPreference` (request) do not share a
value space.

## 2. `swap.value` is hex-encoded while every other integer is decimal

Within one response:

```json
"quote": { "input": { "amount": "1000000" } }        // decimal string
"swap":  { "value": "0x00", "gasLimit": "163675" }   // hex string, decimal string
```

`value` is the only hex-encoded integer we found. It is easy to copy straight
into a transaction builder — where `"0x00"` may be accepted — or into a typed
schema expecting decimal digits, where it fails validation late and confusingly.
Ours required `^[0-9]+$`, so it failed at the boundary; had it not, we would
have shipped a wrong value.

**Suggestion:** make it a decimal string like the sibling fields, or document
the difference next to it. If it must stay hex for eth-JSON-RPC compatibility,
consider `valueHex` so the encoding is visible in the name.

## 3. No quote expiry in the response

The response has no field saying when the quote stops being usable. Classic
routes are priced against a specific block, and `quote.blockNumber` is present,
but the mapping from block to wall-clock validity is left to the integrator. We
imposed a conservative local 45-second TTL — a guess, and one that is either
wastefully short or dangerously long depending on conditions we cannot see.

For an autonomous agent this matters more than for a UI: there is no human
watching, and the gap between quoting and submitting is not bounded by how fast
someone clicks. `permitData.values.sigDeadline` exists but is ~30 days out, so
it is not a proxy for quote freshness.

**Suggestion:** return `expiresAt` (or `validUntilBlock`). Even a conservative
server-side value beats every integrator inventing their own.

## 4. Contract callers can't use the suggested Permit2 flow — and the docs only describe that one

This is the one that required a real design decision, and it is likely to affect
any protocol integrating you rather than any wallet.

`/quote` returns a `permitData` block to be signed as an EIP-712 `PermitSingle`.
**Our swapper is a smart contract vault. It holds no private key and cannot
produce a signature.** The documented path is simply unavailable to it.

The workaround is Permit2's other entry point — calling
`approve(token, spender, amount, expiration)` directly, an ordinary transaction
a contract can make — which yields the same allowance with no signature. That
works, and `POST /swap` happily returns 200 with no signature supplied, which is
how we confirmed the approach was supported rather than merely tolerated.

But we established that by experiment. Nothing in the docs said whether omitting
the signature was supported or whether we were relying on undefined behaviour
that might change. For an autonomous agent holding user funds, "it returned 200
in July" is an uncomfortable foundation.

**Suggestion:** document the contract-caller path explicitly — that
`permitData` may be ignored when the swapper has a standing Permit2 allowance,
and that `/swap` will build the calldata regardless. A one-line
`"requiresSignature": false` in the response when a standing allowance is
detected would be even better. Smart-account and protocol integrations are only
going to become more common, and right now that audience has to discover its own
path.

## 5. Small things that went right

Worth recording, since feedback skewed negative by construction:

- **`x-api-key` header auth, no OAuth dance.** Key to working quote in minutes.
- **Validation errors name the valid values.** Item 1 above would have been an
  hour of guessing with a bare `400 Bad Request`.
- **`/swap` accepting the `quote` object verbatim** is the right shape. No
  reconstructing a request from a response, no field-by-field remapping.
- **`route` carries token `symbol` and `decimals`.** We render a human-readable
  "swap 1,000 USDC for ~0.31 WETH" for the agent's decision feed straight from
  the quote, with no extra token-metadata lookup. Small thing, saved a call.
- **`gasFeeUSD` alongside `gasFee`.** Useful for an agent deciding whether a
  rebalance is worth its cost.

---

## Summary

| # | Item | Impact |
|---|---|---|
| 1 | `CLASSIC` rejected on request, echoed on response | first-attempt 400 |
| 2 | `swap.value` hex while siblings are decimal | silent wrongness risk |
| 3 | No quote expiry field | every integrator invents a TTL |
| 4 | Contract-caller Permit2 path undocumented | required experiment; the fix works but is unwritten |

Items 3 and 4 matter most for autonomous/contract integrations. Item 4 in
particular is a documentation gap rather than a missing capability — the
capability is there and works well.
