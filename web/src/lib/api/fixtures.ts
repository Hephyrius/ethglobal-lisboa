import {
  AgentAction,
  Mandate,
  MarketSnapshot,
  VaultState,
  type AgentAction as AgentActionT,
  type Mandate as MandateT,
  type MarketSnapshot as MarketSnapshotT,
  type VaultState as VaultStateT,
} from '@curator/schema'

import agentActionJson from '../../../../packages/schema/fixtures/agent-action.json'
import mandateJson from '../../../../packages/schema/fixtures/mandate.json'
import marketSnapshotJson from '../../../../packages/schema/fixtures/market-snapshot.json'
import vaultStateJson from '../../../../packages/schema/fixtures/vault-state.json'

/**
 * The golden fixtures, parsed through the zod mirror at module load.
 *
 * Two things worth knowing:
 *
 * 1. **Parsing eagerly is on purpose.** Wave 0's `test_conformance.py` checks
 *    every fixture against the JSON Schema and the *pydantic* mirror; nothing
 *    checked them against the *zod* mirror. Parsing here at boot closes that
 *    half of the drift risk — if the TypeScript and JSON representations ever
 *    disagree, the app fails immediately and loudly rather than rendering
 *    something subtly wrong in front of a judge.
 *
 * 2. **`agent-action.json` carries no `snapshot`,** but its `facts_used` are
 *    exactly `f1…f6` — the ids in `market-snapshot.json`. The two fixtures are
 *    a matched pair, so we attach one to the other. Without that the decision
 *    feed has decisions with no data to trace them back to, which is precisely
 *    the link this app exists to draw.
 *
 * Everything below is development scaffolding. It renders only when the mode
 * badge says FIXTURES; the demo path is live data.
 */

export const FIXTURE_MANDATE: MandateT = Mandate.parse(mandateJson)
export const FIXTURE_SNAPSHOT: MarketSnapshotT = MarketSnapshot.parse(marketSnapshotJson)
export const FIXTURE_VAULT_STATE: VaultStateT = VaultState.parse(vaultStateJson)
export const FIXTURE_ACTION: AgentActionT = AgentAction.parse({
  ...agentActionJson,
  snapshot: marketSnapshotJson,
})

export function fixtureMandate(): MandateT {
  return FIXTURE_MANDATE
}

export function fixtureVaultState(address: string): VaultStateT {
  return { ...FIXTURE_VAULT_STATE, address: normalizeAddress(address) }
}

/**
 * Shift a snapshot back in time and nudge the rate-like facts, so the feed does
 * not read as the same row printed three times. Deterministic by construction —
 * `Math.random()` here would desynchronise the server and client renders and
 * produce a hydration mismatch.
 */
function shiftSnapshot(snapshot: MarketSnapshotT, minutesAgo: number, drift: number): MarketSnapshotT {
  const shift = (iso: string) => new Date(Date.parse(iso) - minutesAgo * 60_000).toISOString()
  return {
    ...snapshot,
    taken_at: shift(snapshot.taken_at),
    facts: snapshot.facts.map((fact) => ({
      ...fact,
      observed_at: shift(fact.observed_at),
      value:
        fact.unit === 'apy_fraction' || fact.unit === 'ratio'
          ? Math.max(0, Number((fact.value * (1 + drift)).toFixed(6)))
          : fact.value,
    })),
  }
}

function shiftTimestamp(iso: string, minutesAgo: number): string {
  return new Date(Date.parse(iso) - minutesAgo * 60_000).toISOString()
}

function normalizeAddress(address: string): string {
  return /^0x[a-fA-F0-9]{40}$/.test(address) ? address : FIXTURE_VAULT_STATE.address
}

/**
 * A feed covering the three states a judge needs to see:
 *
 * - `executed` — the full causal chain, data → reasoning → transaction.
 * - `held`     — "hold" is a first-class answer; an agent that never holds is
 *                churning the vault, not curating it.
 * - `rejected` — the model produced output that failed schema validation three
 *                times, so no decision exists and nothing reached the chain.
 *                This is the only visible evidence that Lane B's validation
 *                layer is load-bearing, which is why the schema says to keep
 *                rejected actions rather than discard them.
 */
const DERIVED_FEED: AgentActionT[] = buildFeed()

export function fixtureDecisions(address: string): AgentActionT[] {
  const vault = normalizeAddress(address)

  // Anchor the newest cycle a few minutes in the past. The golden fixtures are
  // stamped 2026-07-25T14:05Z, and rendered raw at any earlier hour they read
  // "in 11 hours" — which looks like a clock bug rather than sample data. The
  // whole feed shifts by one constant so the intervals between cycles, which
  // the reasoning refers to ("the last rebalance was 41 minutes ago"), stay
  // exactly as authored.
  //
  // Safe to use the wall clock here: this runs inside a React Query queryFn,
  // which is client-only, so it cannot desynchronise a server render.
  const delta = Date.now() - Date.parse(DERIVED_FEED[0].timestamp) - 4 * 60_000

  return DERIVED_FEED.map((action) => shiftAction(action, vault, delta))
}

function shiftAction(action: AgentActionT, vault: string, deltaMs: number): AgentActionT {
  const shift = (iso: string) => new Date(Date.parse(iso) + deltaMs).toISOString()
  return {
    ...action,
    vault,
    timestamp: shift(action.timestamp),
    snapshot: action.snapshot
      ? {
          ...action.snapshot,
          taken_at: shift(action.snapshot.taken_at),
          facts: action.snapshot.facts.map((fact) => ({
            ...fact,
            observed_at: shift(fact.observed_at),
          })),
        }
      : undefined,
  }
}

/**
 * Built once at module load, not per call — so these hand-authored actions are
 * validated against the zod mirror at import time. Any drift fails the Next
 * build (this module is imported by the landing page, which is prerendered)
 * rather than throwing in a click handler during a demo.
 */
function buildFeed(): AgentActionT[] {
  const base = FIXTURE_ACTION
  const vault = FIXTURE_VAULT_STATE.address

  const executed: AgentActionT = { ...base, vault }

  /**
   * An Aqua ship, with SwapVM program parameters.
   *
   * The 1inch centrepiece (e2e plan R5) is blocked on Lanes B and D, so no real
   * ship has ever reached this UI. Carrying one as a fixture means the SwapVM
   * rendering path is exercised and visually checked *now* rather than
   * discovered broken the first time a real one lands.
   *
   * Both approvals are present deliberately. Cross-lane request #17: `ship()`
   * succeeds with zero allowance and leaves a position that looks healthy in
   * every observable way and is silently unfillable — so a plan that shows the
   * approvals is the plan shape worth teaching a reader to expect.
   */
  const shipped: AgentActionT = AgentAction.parse({
    id: 'act_000043',
    vault,
    timestamp: shiftTimestamp(base.timestamp, -18),
    status: 'executed',
    snapshot: shiftSnapshot(FIXTURE_SNAPSHOT, -18, 0.01),
    decision: {
      action: 'enter',
      reasoning:
        'Holding both legs at the 50/50 target with no rotation required, so the idle inventory can earn rather than sit. Shipping the full book into Aqua as a maker: the tokens never leave the vault — Aqua tracks a virtual balance against them — so totalAssets() is unchanged and a redemption is still honoured from the same USDC. A constant-product curve suits a pair I am willing to be filled on in either direction, and 30bp covers the inventory risk at this depth without pricing the quote out of the market.',
      facts_used: ['f5', 'f6'],
      venue_intents: [
        {
          venue: 'aqua',
          kind: 'ship',
          tokens: ['USDC', 'WETH'],
          amounts: ['1249000000', '672232000000000000'],
          program: { shape: 'xyc', fee_bps: 30 },
        },
      ],
      confidence: 0.71,
    },
    plan: {
      venue: 'aqua',
      steps: [
        {
          target: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
          value: '0',
          calldata: '0x095ea7b3000000000000000000000000499943e74fb0ce105688beee8ef2abec5d936d31',
          why: 'approve Aqua to draw 1,249 USDC when a taker fills',
        },
        {
          target: '0x4200000000000000000000000000000000000006',
          value: '0',
          calldata: '0x095ea7b3000000000000000000000000499943e74fb0ce105688beee8ef2abec5d936d31',
          why: 'approve Aqua to draw 0.672232 WETH when a taker fills',
        },
        {
          target: '0x499943E74FB0cE105688beeE8Ef2ABec5D936d31',
          value: '0',
          calldata: '0x2f2ff15d00000000000000000000000000000000000000000000000000000000000000c0',
          why: 'ship the SwapVM program into Aqua as a maker strategy',
        },
      ],
      expected_effect: 'post a two-sided USDC/WETH quote as an Aqua maker; tokens stay in the vault',
    },
    tx_hashes: [
      '0xc3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff001122',
      '0xd4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00112233',
      '0xe5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff0011223344',
    ],
    model: { backend: 'ollama', name: 'qwen2.5:14b-instruct', validation_retries: 0 },
    error: null,
    duration_ms: 11240,
  })

  const held: AgentActionT = AgentAction.parse({
    id: 'act_000041',
    vault,
    timestamp: shiftTimestamp(base.timestamp, 25),
    status: 'held',
    snapshot: shiftSnapshot(FIXTURE_SNAPSHOT, 25, -0.04),
    decision: {
      action: 'hold',
      reasoning:
        'The Morpho Blue premium over Aave is 141bp this tick, down from 155bp, and the last rebalance was 41 minutes ago against a 3600s cooldown. Rotating now would pay roughly 12bp of slippage to capture a spread that has been compressing for two consecutive reads, and the cooldown does not clear for another 19 minutes regardless. Holding is the cheaper expression of the same view: the position I would open is the position I already have.',
      facts_used: ['f1', 'f2', 'f4'],
      confidence: 0.74,
    },
    model: { backend: 'ollama', name: 'qwen2.5:14b-instruct', validation_retries: 0 },
    error: null,
    duration_ms: 5130,
  })

  const rejected: AgentActionT = AgentAction.parse({
    id: 'act_000040',
    vault,
    timestamp: shiftTimestamp(base.timestamp, 58),
    status: 'rejected',
    snapshot: shiftSnapshot(FIXTURE_SNAPSHOT, 58, 0.07),
    model: { backend: 'ollama', name: 'qwen2.5:14b-instruct', validation_retries: 3 },
    error:
      'Model output failed AllocationDecision validation 3 times and was discarded without touching the chain. Last failure: venue_intents.0.pct_of_holdings = 1.4 (expected <= 1), and facts_used referenced "f9", which was not in the snapshot the model was given.',
    duration_ms: 21480,
  })

  return [shipped, executed, held, rejected]
}

/** A single fresh action, for the "run agent tick" button in fixture mode. */
export function fixtureTick(address: string): AgentActionT {
  const [latest] = fixtureDecisions(address)
  return {
    ...latest,
    id: 'act_000043',
    // Deliberately *not* Date.now() at module scope — this runs in a click
    // handler, so it is client-only and cannot desynchronise a server render.
    timestamp: new Date().toISOString(),
  }
}
