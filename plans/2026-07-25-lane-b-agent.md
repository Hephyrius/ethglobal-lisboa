# Lane B — Agent harness · `/agent`

**Owner:** Lane B instance · **Claimed:** 2026-07-25 T+1:00 · **Scope:** §10 Lane B MVP only

The curator itself: the model seam, output validation, the mandate, the decision loop, the chain
client, and the FastAPI surface Lane E consumes.

---

## 1. The two things that decide whether this lane succeeds

**Lane E is blocked until the frozen routes answer.** Everything else in this plan is sequenced
behind getting §8's five routes up and returning schema-valid fixture data. That is phase 1 and it
ships before the model layer exists.

**The agent holds a key.** `plans/initiate_plan.md` §2 locks *agent holds a key and executes
directly*, with no human override after genesis and no on-chain backstop. The only thing standing
between a 14B open-weight model's malformed JSON and a signed transaction is
`agent/model/validation.py`. It is treated as the most important file in the lane, tested first, and
it fails closed.

---

## 2. Approach — late-bound providers, so nothing blocks and nothing couples

Lanes C (data) and D (venues) do not exist yet, and Rule 7 forbids importing their internals anyway.
The harness therefore never imports a concrete source or venue **at all** — not even later.

Providers are resolved at runtime from a `"module:attribute"` string in config:

```
AGENT_DATA_REGISTRY=data.registry:registry      # Lane C's DataSourceRegistry
AGENT_VENUE_REGISTRY=venues:registry            # Lane D's Venue registry
```

Unset (the default) → the fixture provider in `agent/providers/` backed by
`packages/schema/fixtures/`. Import fails → log, fall back to fixtures, keep serving.

Three properties fall out of this, all of them required by the plan:

- The mandate's `permitted_data_sources` is the *only* thing that names a source. The harness passes
  those keys straight to `DataSourceRegistry.snapshot()`, exactly as the master plan's Lane B bullet
  demands ("resolve by name from the mandate; never import a source directly"). Granting a new source
  is a mandate edit, not a code change.
- Lane C and Lane D landing requires **zero** edits in `/agent` — one env var each.
- `import agent` never transitively imports another lane, so a broken lane cannot break this one.

Lane A is handled the same way but simpler: ABIs are *read* from `contracts/out/**` at runtime
(they're committed on purpose, per `docs/active-work.md`), with a minimal hand-written ABI subset as
the fallback so `VaultClient` compiles and tests run before CP1.

## 3. Mode switch — the same routes, fixture or live

`AGENT_MODE=fixture|live` (default `fixture`). It swaps *dependencies*, never handler code, so the
route Lane E integrates against in hour 2 is byte-identical to the one running at the demo. There is
no "fixture endpoint" to migrate off.

---

## 4. File breakdown

```
agent/
  README.md              usage doc — Lane E's integration surface (Rule 5)
  config.py              env-driven settings; no absolute paths (§3 cross-platform)
  fixtures.py            loads packages/schema/fixtures/*.json, repo-root-relative

  model/                 ── the model seam
    openai_compat.py     one OpenAI-compatible /chat/completions client over httpx
    backends/ollama.py   ModelBackend impl (+ Ollama's json format hint)
    backends/vllm.py     ModelBackend impl (+ guided_json hint)
    backends/scripted.py deterministic offline backend — tests and fixture mode
    backends/__init__.py registration table: one line per backend
    validation.py        ★ LOAD-BEARING — extract → schema → constraints → retry
    prompts/curator.py   system + decision prompt, snapshot rendering
    prompts/genesis.py   genesis chat prompt, mandate-draft extraction

  mandate/
    store.py             load / persist (JSON on disk, one file per vault)
    hashing.py           canonical JSON → keccak256 → mandate_hash
    amend.py             agent-side mutation: patch merge, re-validate, update_rules guard

  loop/
    engine.py            DecisionEngine: mandate + snapshot → validated AllocationDecision
    constraints.py       mandate checks, separated so they're testable without a model
    cycle.py             one tick: snapshot → decide → plan → execute → AgentAction
    store.py             AgentAction persistence, append-only JSONL per vault

  chain/
    abi.py               load Lane A ABIs from contracts/out; minimal fallback
    vault_client.py      VaultClient over web3.py
    stub.py              fixture-backed VaultClient — used until Lane A publishes

  providers/
    resolve.py           the "module:attribute" late binding described in §2
    fixture_data.py      DataSourceRegistry over the golden MarketSnapshot
    fixture_venue.py     Venue over the golden ExecutionPlan

  api/
    app.py               FastAPI factory + CORS for Lane E's dev server
    schemas.py           request/response models mirroring the zod API contract
    deps.py              dependency providers, mode-aware
    routes/genesis.py    POST /genesis/chat · POST /genesis/finalize
    routes/vault.py      GET state · GET decisions · POST tick

  tests/                 pytest; §12 DoD lives here
```

No file is planned above ~200 lines (Rule 3). `validation.py`, `constraints.py` and `cycle.py` are
deliberately three files rather than one "agent core" — the constraint checks must be testable
without a model, and the retry logic without a chain.

---

## 5. Validation design — why reject-and-retry is structured this way

Four layers, each producing an error string specific enough to *teach the model on the retry*:

| Layer | Catches | Retry hint fed back |
|---|---|---|
| 1 · extract | prose around JSON, ```json fences, doubled objects | "return only a JSON object" |
| 2 · schema | wrong types, unknown fields (`extra="forbid"`), bad enums | the pydantic error, verbatim |
| 3 · mandate | asset not in `allowed_assets`, weights ≠ 1, slippage over ceiling, too many intents | the specific breach + the limit |
| 4 · grounding | `facts_used` naming a `Fact.id` not in the snapshot | the ids it invented + the ids available |

Layer 4 is the one that matters beyond schema-correctness. `packages/schema/README.md` calls it out:
`facts_used` must reference real ids, both so the dApp can draw data → reasoning → tx and so we
catch a model inventing numbers. A hallucinated fact id is the cheapest available signal that the
reasoning is confabulated, and it is worth a retry.

Max 3 attempts, then the cycle records `AgentAction(status="rejected")` with the error and
`ModelProvenance.validation_retries`, and **nothing is sent to a venue or the chain**. Those records
are kept deliberately — per the schema README they are the evidence that this layer is load-bearing,
and they render in Lane E's feed.

---

## 6. Interfaces produced

**For Lane E** — the five frozen routes from §8, unchanged, plus `GET /health` and
`GET /genesis/sources` (the registry's `available()` keys, so the genesis UI can offer the user real
data-source choices rather than a hardcoded list). Documented in `agent/README.md`.

**For everyone** — `DecisionEngine`, `ModelBackend` and `VaultClient` implementations conforming to
`curator_schema.ports`. Lane E can mock the engine against the Protocol.

**Consumed** — `DataSourceRegistry` (Lane C), `Venue` (Lane D), ABIs + `deployments/base-fork.json`
(Lane A). All three via ports and published artifacts, never source.

---

## 7. Order of work

| Phase | Deliverable | Gate |
|---|---|---|
| **1** | Config, fixtures, API skeleton, all five routes returning fixture data, route tests | **Unblocks Lane E — first push** |
| **2** | Model seam + `validation.py` + retry tests (deliberately malformed output → recovery) | §12 DoD line 1 |
| **3** | Mandate store/hash/amend; `DecisionEngine`; constraint tests | |
| **4** | `cycle.py` + `AgentAction` store; `POST /tick` runs the real loop in live mode | CP2 |
| **5** | `VaultClient` on web3.py against Lane A's ABIs; stub until then | CP2 |
| **6** | Genesis chat → mandate draft → finalize → deploy | |
| — | README + build log updated *within* each phase, not after | Rule 1/5 |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| A 14B model emits unusable JSON repeatedly | 4-layer validation with error-specific retries; `scripted.py` backend keeps tests hermetic; failure is a recorded `rejected` action, not an exception |
| Datetime format drift Python↔TS: zod's `.datetime()` rejects `+00:00`, pydantic can emit it | Pin UTC-with-`Z` serialization in `api/app.py` and assert it in a route test — a wire-format bug that only shows up in Lane E's browser is the expensive kind |
| Lane A's ABI shape differs from my assumption | `execute(address,uint256,bytes)` is frozen in the master plan §10; `abi.py` prefers the published ABI and only falls back to the minimal one |
| Ollama not running on the demo machine | Backend health check at startup; `/health` reports model reachability; fixture mode always works |
| `uv` and Ollama on macOS at 10:00 | No absolute paths; model host from `.env`; setup steps in the README |

---

## 9. Definition of done

- [ ] All five frozen routes schema-valid in both modes; `agent/README.md` documents each
- [ ] `pytest agent` green, including malformed-output recovery and constraint rejection
- [ ] Loop runs end-to-end in fixture mode with no network
- [ ] Lane C's registry and Lane D's venues drop in via env var alone — no code change
- [ ] Build-log entries for late binding, validation layering, and every library choice
- [ ] Pushed continuously; claim released in `docs/active-work.md`
