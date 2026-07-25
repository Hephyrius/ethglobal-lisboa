# Lane D — Venues (`/venues`)

**Owner:** Lane D instance · **Claimed:** 2026-07-25 02:10 · **Scope:** master plan §10 Lane D MVP

Lane D owns both sponsor *execution* paths and nothing else. It turns a `VenueIntent` into an
`ExecutionPlan` — concrete calldata the vault executes. It never touches `/contracts`.

---

## 1. What this lane is responsible for

| | |
|---|---|
| **Uniswap** | Taker side. Rotates *what the vault holds* ("volatility spiked → move to stables"). Trading API `/quote` → `/swap` → calldata. |
| **1inch Aqua + SwapVM** | Maker side. *Holds* the position. Tokens never leave the vault; only virtual balances move. `ship()` / `dock()`. |

The two roles are deliberately non-overlapping — [initiate_plan.md](initiate_plan.md) §7 requires 1inch
to be structurally distinct from Uniswap or it reads as cosmetic to judges.

**Why Aqua is the only venue compatible with our locked custody decision.** Pattern 1 says the vault
is sole custodian. A normal AMM LP position transfers tokens out to a pool contract, which breaks
that invariant and corrupts `totalAssets()`. Aqua tracks
`balances[maker][app][strategyHash][token]` on-chain while the tokens **stay in the maker's wallet**.
The vault *is* the maker: `approve(aqua)` once, `ship()` a strategy, capital never moves. That is not
a convenient coincidence — it is the reason 1inch is load-bearing here rather than decorative.

---

## 2. Interfaces produced and consumed

**Produces** — the frozen `Venue` port from `packages/schema/python/curator_schema/ports.py`:

```python
class Venue(Protocol):
    key: str
    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan: ...
```

Both adapters implement exactly this. Lane B calls `plan()` and hands the result to
`VaultClient.execute()`. Adding a third venue is a new adapter, not a refactor anywhere else.

**Consumes:** `VenueIntent` (`SwapIntent` | `AquaShipIntent` | `AquaDockIntent`), `VaultState`, and
`packages/schema/fixtures/*.json` for development. Nothing from Lanes A, B, C, or E at build time.

**Hard contract on every emitted plan** (from the port docstring, and what makes plans safe):
1. Every `step.target` is on the vault allowlist — else `execute()` reverts.
2. Approvals are ordered **before** the call that needs them.
3. `expected_slippage_bps` is populated where the venue can estimate it; the harness rejects plans
   exceeding the mandate ceiling.
4. `quote_expires_at` is set whenever the plan embeds a router quote — stale quotes must not submit.

---

## 3. File breakdown

```
venues/
  pyproject.toml          own uv project — see §6
  README.md               THE integration surface for Lane B (Rule 5)
  ports.py                re-export of the frozen Venue port + shared venue errors
  config.py               env loading (UNISWAP_API_KEY, RPC), Base addresses in one place
  addresses.py            verified Base mainnet constants — single source of truth
  uniswap/
    client.py             Trading API HTTP client: /quote, /swap. Auth, retries, errors.
    plan.py               quote+swap response  ->  ExecutionPlan (approval ordering lives here)
    venue.py              UniswapVenue implements Venue
  aqua/
    program.py            eth_call into SwapVMProgramBuilder -> program bytes
    calldata.py           ship() / dock() ABI encoding, useAquaInsteadOfSignature = true
    venue.py              AquaVenue implements Venue
    solidity/             STANDALONE Foundry project (not /contracts, never imported by Lane A)
      src/SwapVMProgramBuilder.sol    view contract using 1inch's official ProgramBuilder
      test/                            forge tests
  tests/                  schema-conformance + live-quote tests
```

One responsibility per module (Rule 3). The split that matters: `client.py` knows HTTP and nothing
about our schema; `plan.py` knows our schema and nothing about HTTP. That keeps the Uniswap API's
response shape from leaking into the frozen interface, and lets `plan.py` be tested against saved
fixtures with no network.

---

## 4. Verified findings — live API, hour 0

Recorded here because they contradict the master plan's assumptions and cost real time to discover.

| Finding | Consequence |
|---|---|
| `routingPreference` must be `BEST_PRICE` or `FASTEST`. `CLASSIC` → HTTP 400 `RequestValidationError`, despite `CLASSIC` being what the response `routing` field echoes back. | Client sends `BEST_PRICE`. Noted in `FEEDBACK.md`. |
| Swap tx `to` on Base = **`0x6fF5693b99212Da76ad316178A184AB56D299b43`**, not the `0x2626664c…e481` UniversalRouter in the golden fixture. Same address is the Permit2 `spender`. | Allowlist correction filed as request 7. |
| `/swap` returns 200 with **no signature** when the flow is allowance-based Permit2. | The vault is a contract and cannot easily produce an EIP-712 signature — so the contract-friendly path (`Permit2.approve`) is viable and no ERC-1271 work is needed. This de-risks the whole Uniswap path. |
| Approval steps target the **token** contract, per the golden fixture. | Filed as request 8 — blocking for CP2 unless Lane A allowlists tokens. |

Live quote proving the key works: 1 USDC → 0.000537935691469946 WETH, v3 0.01% pool, priceImpact 0.01.

---

## 5. Build order

1. **Hour 0 (done).** Uniswap key verified live; `.env` confirmed gitignored *before* touching it.
2. Package skeleton + `addresses.py` + config.
3. `uniswap/` — client, plan builder, venue. Test against saved fixtures **and** one live call.
4. `aqua/solidity/` — Foundry project, `SwapVMProgramBuilder`, `forge build` green.
5. `aqua/` Python — program bytes via `eth_call`, `ship()`/`dock()` calldata.
6. README + FEEDBACK.md + build-log entries. (~20% of lane time, budgeted, not trailing.)

Uniswap goes first: it is a $10K track gated on a key that is already working, and it has no
dependency on Foundry being installed. Aqua second — higher risk, needs the WSL toolchain.

---

## 6. Risks and how each is handled

| Risk | Handling |
|---|---|
| **Root `pyproject.toml` was broken** — `curator-schema` declared both as workspace member and path source, so `uv sync` failed for Lanes B, C and D. | Lane B fixed and pushed it (request 4). `/venues` additionally carries its own `pyproject.toml` so this lane's dependency set is explicit and installable on its own — that is also what makes the macOS handoff a single `uv sync`. |
| **SwapVM program encoding is the single hardest thing in this lane.** | Do not reimplement 1inch's encoding in Python. Build programs in Solidity with their *official* `ProgramBuilder`, read via `eth_call`, treat the result as opaque bytes. Master plan §14 already names this; it is the whole reason `aqua/solidity/` exists. |
| **`useAquaInsteadOfSignature = true` is what 1inch scores higher.** Easy to leave false and silently lose points. | Set explicitly, asserted in a test, documented in the README. |
| Router quotes go stale between plan and execution. | `quote_expires_at` populated on every Uniswap plan; the harness enforces it. |
| Foundry not installed / wrong WSL distro. | `wsl -d Ubuntu-24.04` only (glibc 2.39). Uniswap path has zero Foundry dependency, so a Foundry failure cannot take the whole lane down. |
| Live API down at demo time. | Saved golden responses in `tests/` let `plan.py` be exercised offline. The *demo path* still uses live calls — fixtures are development-only (master plan §9.3). |
| Lane A's allowlist disagrees with my targets → every plan reverts. | Requests 7 and 8 filed at hour 0 rather than discovered at CP2. Default to the golden-fixture shape until Lane A rules. |

---

## 7. Definition of done for this lane

- [ ] `POST /quote` returns a live route; `UniswapVenue.plan()` emits a schema-valid `ExecutionPlan`
- [ ] `SwapVMProgramBuilder` `eth_call` returns non-empty program bytes
- [ ] `AquaVenue.plan()` emits a schema-valid `ExecutionPlan` with `useAquaInsteadOfSignature = true`
- [ ] Both validate against `packages/schema/execution-plan.schema.json`, not just the pydantic mirror
- [ ] `venues/README.md` complete enough that Lane B integrates without reading any source
- [ ] `FEEDBACK.md` written + Uniswap Developer Feedback Form submitted
- [ ] Build-log entries for every non-trivial decision
- [ ] Claim released in `docs/active-work.md`
