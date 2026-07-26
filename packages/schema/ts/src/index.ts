/**
 * Zod mirror of the frozen JSON Schemas in packages/schema/*.json.
 *
 * The JSON Schema files are the source of truth; this is the TypeScript view.
 * If the two disagree, the JSON is right. The shared golden fixtures in
 * packages/schema/fixtures/ are validated against both, which is what keeps
 * the Python and TypeScript sides from drifting.
 *
 * FROZEN after Wave 0. Need a change? File a request in docs/active-work.md.
 */

import { z } from 'zod'

// uint256 exceeds Number.MAX_SAFE_INTEGER, so amounts cross the boundary as
// decimal strings. Never parse these with Number().
export const Uint256Str = z.string().regex(/^[0-9]+$/, 'expected uint256 decimal string')
export const Address = z.string().regex(/^0x[a-fA-F0-9]{40}$/, 'expected 0x address')
export const Bytes32 = z.string().regex(/^0x[a-fA-F0-9]{64}$/, 'expected 0x bytes32')
export const HexData = z.string().regex(/^0x([a-fA-F0-9]{2})*$/, 'expected 0x-prefixed hex')

// ── Mandate ───────────────────────────────────────────────────────────────

export const MandateConstraints = z
  .object({
    allowed_assets: z.array(z.string()).min(1),
    max_slippage_bps: z.number().int().min(0).max(10_000),
    max_position_pct: z.number().min(0).max(1).default(1),
    min_cash_pct: z.number().min(0).max(1).default(0),
    rebalance_cooldown_seconds: z.number().int().min(0).default(3600),
    max_actions_per_tick: z.number().int().min(1).default(3),
    /** Soft band on the ALLOCATION AND EXPOSURE constraints only. A breach no
     *  larger than the band is accepted with a warning on the AgentAction rather
     *  than rejected — 61% against a 60% cap is a swap that priced a hair
     *  differently, not a change of intent.
     *
     *  RELATIVE to the constraint's own value, never absolute percentage points:
     *  a ceiling C admits C*(1+band), a floor F admits F*(1-band), a target T
     *  admits |actual-T| <= T*band.
     *
     *  Applies to max_position_pct, min_cash_pct, target-allocation drift.
     *  NEVER to max_slippage_bps (a ceiling already compared against a
     *  worst-case bound, so banding it silently pays more than the mandate's
     *  stated maximum cost), never to the asset/venue/source allowlists (not
     *  numeric), never to the anti-churn limits (a band there is just a bigger
     *  limit). 0 restores strict rejection. */
    tolerance_band_pct: z.number().min(0).max(0.5).default(0.05),
  })
  .strict()

/** How the agent argues, and what it prefers among options already permitted.
 *
 *  INVARIANT: a persona SKEWS PREFERENCE INSIDE the permitted set and can never
 *  widen it. An aggressive persona may prefer the riskier of two permitted
 *  assets; it may not reach an asset allowed_assets omits, raise a cap, shrink
 *  the cash floor, or loosen the slippage ceiling. Persona is taste; constraints
 *  are law. Render it as character, never as authority. */
export const Persona = z
  .object({
    name: z.string().min(1).max(80),
    /** How it writes its reasoning — it shapes the text a depositor reads, not
     *  the bounds the harness enforces. */
    voice: z.string().min(1).max(500),
    /** Each a preference between options the mandate already allows. */
    biases: z.array(z.string().min(1).max(200)).max(10).default([]),
    /** Steers sizing WITHIN max_position_pct and how often it holds. Changes no bound. */
    conviction: z.enum(['low', 'medium', 'high']).default('medium'),
  })
  .strict()

export const Mandate = z
  .object({
    version: z.number().int().min(1),
    name: z.string().min(1).max(80),
    objective: z.string().min(1).max(2000),
    base_asset: z.string(),
    constraints: MandateConstraints,
    /** Registry keys resolved by the data layer. Granting a source is a
     *  mandate edit, not a code change — the extension point for new providers. */
    permitted_data_sources: z.array(z.string()).min(1),
    /** Closed on purpose: a mandate naming a venue with no adapter yields an
     *  agent whose every proposal the harness must reject. 'morpho' joined in
     *  Wave 3 — it had shipped with supply and withdraw paths and was published
     *  as one of four while this list held three. */
    permitted_venues: z.array(z.enum(['uniswap', 'aqua', 'aave', 'morpho'])).min(1),
    created_at: z.string().datetime().optional(),
    risk_posture: z.enum(['conservative', 'balanced', 'aggressive']).default('balanced'),
    /** Optional character the agent argues in. Absent means a neutral curator. */
    persona: Persona.optional(),
    update_rules: z.string().max(1000).optional(),
  })
  .strict()

// ── MarketSnapshot ────────────────────────────────────────────────────────

export const FactKind = z.enum([
  'yield',
  'price',
  'tvl',
  'liquidity',
  'volatility',
  'utilization',
  'volume',
  /** Normalised 0-1 market-mood index; 0 is extreme fear, 1 extreme greed. */
  'sentiment',
  /** What it costs to transact — why a 3 bps edge may not be worth chasing. */
  'gas',
  /** Market-implied likelihood of ONE NAMED EVENT. Not folded into 'sentiment':
   *  a mood index has no event attached, so a consumer filtering on one must not
   *  silently receive the other. The only forward-looking kind in this list. */
  'probability',
])

/** 'probability' is 0-1 and, unlike 'ratio', bounded and complementary — a
 *  binary market's two outcomes sum to 1, so one may be subtracted from the
 *  other, which is never safe for a ratio. Render it as "75.2% chance". */
export const FactUnit = z.enum([
  'apy_fraction',
  'usd',
  'ratio',
  'bps',
  'token_amount',
  'probability',
])

export const FactSubject = z
  .object({
    protocol: z.string().optional(),
    market: z.string().optional(),
    token: z.string().optional(),
    pair: z.tuple([z.string(), z.string()]).optional(),
    chain: z.string().default('base'),
  })
  .strict()

/** One observation carrying its own provenance. Deliberately generic: a source
 *  describes what it knows and leaves the rest unset. */
export const Fact = z
  .object({
    id: z.string(),
    kind: FactKind,
    subject: FactSubject,
    value: z.number(),
    /** apy_fraction is 0.0432 for 4.32%. Normalized at the source adapter. */
    unit: FactUnit,
    /** Registry key of the contributing source — render this as provenance. */
    source: z.string(),
    observed_at: z.string().datetime(),
    confidence: z.number().min(0).max(1).optional(),
  })
  .strict()

export const SourceError = z.object({ source: z.string(), message: z.string() }).strict()

/** Context about a source that is NOT a failure — a structural
 *  non-applicability, or a deliberate skip. Rendered differently from an
 *  error, because a category mistake shown as a gap teaches the agent (and the
 *  reader) to distrust a feed that is working. */
export const SourceNote = z.object({ source: z.string(), message: z.string() }).strict()

/** Source-agnostic by construction: a flat list of facts, not a provider's
 *  response shape. */
export const MarketSnapshot = z
  .object({
    taken_at: z.string().datetime(),
    facts: z.array(Fact).default([]),
    /** A failing source degrades the snapshot; it never crashes the loop.
     *  Worth surfacing in the UI — it shows what the agent could not see. */
    errors: z.array(SourceError).default([]),
    notes: z.array(SourceNote).default([]),
  })
  .strict()

// ── AllocationDecision ────────────────────────────────────────────────────

export const TargetAllocation = z
  .object({ asset: z.string(), weight: z.number().min(0).max(1) })
  .strict()

export const SwapIntent = z
  .object({
    venue: z.literal('uniswap'),
    kind: z.literal('swap'),
    token_in: z.string(),
    token_out: z.string(),
    amount_in: Uint256Str.optional(),
    pct_of_holdings: z.number().min(0).max(1).optional(),
  })
  .strict()

export const AquaProgram = z
  .object({
    shape: z.enum(['xyc', 'pegged']).default('xyc'),
    fee_bps: z.number().int().min(0).max(10_000).optional(),
  })
  .strict()

export const AquaShipIntent = z
  .object({
    venue: z.literal('aqua'),
    kind: z.literal('ship'),
    tokens: z.array(z.string()).min(1),
    amounts: z.array(Uint256Str).min(1),
    program: AquaProgram.optional(),
  })
  .strict()

export const AquaDockIntent = z
  .object({
    venue: z.literal('aqua'),
    kind: z.literal('dock'),
    strategy_hash: Bytes32,
  })
  .strict()

/** Deposit into a lending market to earn interest. Custody is preserved: the
 *  vault supplies and holds the aToken itself, and `onBehalfOf` is always the
 *  vault. Closes the gap where the agent read Aave yields it could not act on. */
export const SupplyIntent = z
  .object({
    // Widened from z.literal('aave') in Wave 3: MorphoVenue was registered,
    // tested and reported available, but routing goes through intent.venue, so
    // the pinned literal made it unreachable from any intent the model could
    // emit. A mandate must still grant 'morpho' in permitted_venues.
    venue: z.enum(['aave', 'morpho']),
    kind: z.literal('supply'),
    asset: z.string(),
    amount: Uint256Str.optional(),
    pct_of_holdings: z.number().min(0).max(1).optional(),
  })
  .strict()

/** Redeem a supplied asset back into the vault. Omit `amount` for all of it. */
export const WithdrawIntent = z
  .object({
    // Widened with SupplyIntent — a venue you can supply to and cannot
    // withdraw from is a one-way door.
    venue: z.enum(['aave', 'morpho']),
    kind: z.literal('withdraw'),
    asset: z.string(),
    amount: Uint256Str.optional(),
  })
  .strict()

export const VenueIntent = z.discriminatedUnion('kind', [
  SwapIntent,
  AquaShipIntent,
  AquaDockIntent,
  SupplyIntent,
  WithdrawIntent,
])

export const MandateAmendment = z
  .object({ rationale: z.string().max(1000), patch: z.record(z.unknown()) })
  .strict()

/** What the LLM must emit. The harness validates and reject-and-retries before
 *  anything reaches the chain. */
export const AllocationDecision = z
  .object({
    /** 'hold' is a first-class answer — a model that never holds churns the vault. */
    action: z.enum(['hold', 'rebalance', 'enter', 'exit']),
    /** Rendered verbatim in the decision feed. This is the product. */
    reasoning: z.string().min(1).max(2000),
    /** Fact ids that drove the decision — lets the UI draw data → reasoning → tx. */
    facts_used: z.array(z.string()).default([]),
    target_allocations: z.array(TargetAllocation).optional(),
    venue_intents: z.array(VenueIntent).optional(),
    confidence: z.number().min(0).max(1).optional(),
    mandate_amendment: MandateAmendment.optional(),
  })
  .strict()

// ── ExecutionPlan ─────────────────────────────────────────────────────────

export const ExecutionStep = z
  .object({
    /** Must be on the vault's allowlist or execute() reverts. */
    target: Address,
    value: Uint256Str.default('0'),
    calldata: HexData,
    why: z.string().max(200),
  })
  .strict()

export const ExecutionPlan = z
  .object({
    venue: z.string(),
    steps: z.array(ExecutionStep).min(1),
    expected_effect: z.string().max(500).optional(),
    expected_slippage_bps: z.number().int().min(0).optional(),
    quote_expires_at: z.string().datetime().optional(),
  })
  .strict()

// ── AgentAction ───────────────────────────────────────────────────────────

export const ModelProvenance = z
  .object({
    backend: z.string().optional(),
    name: z.string().optional(),
    /** Malformed outputs rejected before a valid one — the honest cost of
     *  small open models. Worth showing rather than hiding. */
    validation_retries: z.number().int().min(0).default(0),
  })
  .strict()

/** One banded acceptance — a constraint that bent and was allowed to.
 *
 *  Structured rather than a pre-formatted sentence so the feed can state which
 *  constraint bent and by how much, and style it as an accepted exception rather
 *  than as a failure. `limit` is what the agent is still steering back toward. */
export const ConstraintWarning = z
  .object({
    /** Closed on purpose: a second warning class is a schema change, so nobody
     *  can quietly record a different kind of exception in this array. */
    kind: z.literal('tolerance_band'),
    /** The MandateConstraints field that bent, or 'target_allocation' for drift. */
    constraint: z.string(),
    /** Asset symbol when the constraint is per-asset; absent for portfolio-wide. */
    subject: z.string().optional(),
    limit: z.number(),
    actual: z.number(),
    /** The band in force when this was accepted — recorded on the action because
     *  the agent may amend its own mandate afterwards. */
    band_pct: z.number().min(0).max(0.5),
    message: z.string().min(1).max(300),
  })
  .strict()

/** One decision cycle. The audit trail and the demo feed. */
export const AgentAction = z
  .object({
    id: z.string(),
    vault: Address,
    timestamp: z.string().datetime(),
    /** 'rejected' = failed validation, never reached the chain. Render these —
     *  they evidence that the validation layer is load-bearing. */
    status: z.enum(['pending', 'executed', 'held', 'rejected', 'failed']),
    snapshot: MarketSnapshot.optional(),
    decision: AllocationDecision.optional(),
    plan: ExecutionPlan.optional(),
    tx_hashes: z.array(Bytes32).default([]),
    mandate_version_before: z.number().int().min(1).optional(),
    mandate_version_after: z.number().int().min(1).optional(),
    model: ModelProvenance.optional(),
    error: z.string().nullable().default(null),
    /** Constraints this cycle breached and was ACCEPTED anyway, inside
     *  tolerance_band_pct. Not an error — a warning rides on a successful
     *  action, so style it as an accepted exception, not a failure. MUST be
     *  rendered wherever the action is: an invisible band is indistinguishable
     *  from there being no rule at all. */
    warnings: z.array(ConstraintWarning).default([]),
    duration_ms: z.number().int().min(0).optional(),
  })
  .strict()

// ── VaultState ────────────────────────────────────────────────────────────

export const Holding = z
  .object({
    token: Address,
    symbol: z.string(),
    balance: Uint256Str,
    decimals: z.number().int().min(0).max(36).optional(),
    value_in_asset: Uint256Str.optional(),
    /** Venue key if this balance backs an open position. Flags encumbrance,
     *  not location — the vault still custodies it. */
    committed_to_venue: z.string().nullable().default(null),
    /** The symbol this holding is economically equivalent to, when it is not
     *  itself — `aBasUSDC` represents `USDC`. Fold it back before computing any
     *  weight: a receipt token is not a new exposure. */
    represents: z.string().nullable().default(null),
  })
  .strict()

export const AquaStrategy = z
  .object({
    strategy_hash: Bytes32,
    tokens: z.array(Address).default([]),
    app: Address.optional(),
    shipped_at: z.string().datetime().optional(),
  })
  .strict()

/** Invariant: the vault is sole custodian (Pattern 1). Capital never leaves it,
 *  so `holdings` is literally the vault's balances. */
export const VaultState = z
  .object({
    address: Address,
    asset: Address,
    total_assets: Uint256Str,
    total_supply: Uint256Str,
    holdings: z.array(Holding).default([]),
    asset_decimals: z.number().int().min(0).max(36).default(6),
    /** Assets per whole share, SCALED BY 1e18 — a dimensionless ratio, not the
     *  base-asset-decimal number convertToAssets(1e18) returns on-chain. Divide
     *  by 1e12 to compare: 1000644584000000000 here is 1000644 there.
     *
     *  ⚠️ VaultPerformance points carry the SAME quantity in the OTHER scale,
     *  deliberately — one vault at one moment read 1000644584000000000 here and
     *  1000644 there. Deriving share price from total_assets/total_supply, as
     *  this dApp already does, sidesteps the question entirely and is still the
     *  recommended path. */
    share_price: z.string().optional(),
    /** Holder of AGENT_ROLE — executes directly, no human override. */
    agent: Address.optional(),
    /** keccak256 of the canonical mandate, recorded at genesis. Lets a
     *  depositor verify the mandate shown is the one deployed. */
    mandate_hash: Bytes32.optional(),
    aqua_strategies: z.array(AquaStrategy).default([]),
    paused: z.boolean().default(false),
    block_number: z.number().int().min(0).optional(),
  })
  .strict()

// ── VaultPerformance ──────────────────────────────────────────────────────

export const AllocationSlice = z
  .object({
    symbol: z.string(),
    value_in_asset: Uint256Str,
    committed_to_venue: z.string().nullable().default(null),
  })
  .strict()

/** One observation of a vault's worth. Never an interpolation: on a pinned fork
 *  blocks advance only when a transaction is mined, so the series is
 *  event-spaced and a flat stretch between two trades is the truth. Plot it
 *  against `timestamp`, and do not smooth it. */
export const PerformancePoint = z
  .object({
    timestamp: z.string().datetime(),
    total_assets: Uint256Str,
    total_supply: Uint256Str,
    block_number: z.number().int().min(0).optional(),
    /** convertToAssets(1e18) in BASE-ASSET decimals — for a 6-decimal asset,
     *  1.0025 is "1002506", not 1e18. Absent while total_supply is 0.
     *  ⚠️ VaultState.share_price is the same quantity scaled by 1e18; multiply
     *  this by 1e12 to compare. Same name, two scales, both deliberate. */
    share_price: z.string().optional(),
    allocation: z.array(AllocationSlice).default([]),
    source: z.enum(['tick', 'sampler', 'backfill']).default('tick'),
  })
  .strict()

/** Derived from the points on every request, never stored. Every figure is
 *  nullable and is null — not zero — when the series is too short to support
 *  it. Render "not enough history" for a null; rendering 0.0% is a claim. */
export const PerformanceSummary = z
  .object({
    observations: z.number().int().min(0),
    first_at: z.string().datetime().nullable().default(null),
    last_at: z.string().datetime().nullable().default(null),
    share_price: z.string().nullable().default(null),
    total_assets: Uint256Str.nullable().default(null),
    /** 0.0123 is +1.23%, matching the apy_fraction convention. */
    return_pct: z.number().nullable().default(null),
    return_24h_pct: z.number().nullable().default(null),
    return_7d_pct: z.number().nullable().default(null),
    annualized_return_pct: z.number().nullable().default(null),
    volatility_pct: z.number().nullable().default(null),
    /** Largest peak-to-trough fall, positive. What a depositor actually feels. */
    max_drawdown_pct: z.number().nullable().default(null),
    /** Annualized return over annualized volatility. Not a Sharpe ratio — no
     *  risk-free rate is subtracted — so do not label it one in the UI. */
    risk_adjusted_return: z.number().nullable().default(null),
  })
  .strict()

export const VaultPerformance = z
  .object({
    vault: Address,
    points: z.array(PerformancePoint).default([]),
    summary: PerformanceSummary,
  })
  .strict()

// ── Frozen API contract (agent/api — implemented by Lane B, consumed by E) ──

export const GenesisChatRequest = z
  .object({
    messages: z.array(z.object({ role: z.enum(['user', 'assistant']), content: z.string() })),
  })
  .strict()

export const GenesisChatResponse = z
  .object({ reply: z.string(), mandate_draft: Mandate.partial().optional() })
  .strict()

export const GenesisFinalizeRequest = z.object({ mandate: Mandate }).strict()

export const GenesisFinalizeResponse = z
  .object({ mandate_hash: Bytes32, deploy_tx: Bytes32, vault: Address })
  .strict()

// ── Inferred types ────────────────────────────────────────────────────────

export type Mandate = z.infer<typeof Mandate>
export type Persona = z.infer<typeof Persona>
export type ConstraintWarning = z.infer<typeof ConstraintWarning>
export type MarketSnapshot = z.infer<typeof MarketSnapshot>
export type Fact = z.infer<typeof Fact>
export type SourceNote = z.infer<typeof SourceNote>
export type AllocationDecision = z.infer<typeof AllocationDecision>
export type VenueIntent = z.infer<typeof VenueIntent>
export type ExecutionPlan = z.infer<typeof ExecutionPlan>
export type ExecutionStep = z.infer<typeof ExecutionStep>
export type AgentAction = z.infer<typeof AgentAction>
export type VaultState = z.infer<typeof VaultState>
export type Holding = z.infer<typeof Holding>
export type AllocationSlice = z.infer<typeof AllocationSlice>
export type PerformancePoint = z.infer<typeof PerformancePoint>
export type PerformanceSummary = z.infer<typeof PerformanceSummary>
export type VaultPerformance = z.infer<typeof VaultPerformance>

/**
 * Archetypes — the constraint envelopes a generated mandate must sit inside.
 *
 * An archetype is BOUNDS, not a template. One click asks the model for a fresh
 * mandate; two clicks on the same card must produce two different vaults.
 *
 * ## This file does not gate anything
 *
 * The gate is Python — `curator_schema.archetypes.check_envelope()`. Lane B
 * calls it before deploying, and nothing here decides whether a mandate may go
 * on-chain, so there is no second implementation to disagree with the first.
 *
 * What this gives the dApp is the type and `describeEnvelope()`, which generates
 * a card's bound lines MECHANICALLY from the same JSON the gate reads. That is
 * the whole reason it exists: a hand-written card can promise a number the
 * envelope does not enforce, and nobody notices until a judge asks. Copy that
 * nobody types cannot drift.
 *
 * Distinct from `presets/`, which are fixed mandates seeding the curator chat.
 */

export const NumericRange = z
  .object({
    min: z.number(),
    max: z.number(),
  })
  .strict()
  .refine((r) => r.min <= r.max, { message: 'range is empty: min > max' })

/** `subset_of` is the ceiling, `must_include` the floor. The ceiling is what
 *  makes "the model invents a strategy and it deploys unread" safe to ship. */
export const SetBound = z
  .object({
    subset_of: z.array(z.string()).min(1),
    must_include: z.array(z.string()).default([]),
    min_count: z.number().int().min(1).default(1),
    /** Absent means subset_of.length. */
    max_count: z.number().int().min(1).optional(),
  })
  .strict()

export const ArchetypePersona = z
  .object({
    required: z.boolean(),
    conviction: z.array(z.enum(['low', 'medium', 'high'])).min(1).optional(),
  })
  .strict()

export const Archetype = z
  .object({
    version: z.number().int().min(1),
    key: z.string().regex(/^[a-z][a-z0-9-]{2,40}$/),
    /** The archetype's name, NOT the generated vault's — the model writes that,
     *  and two vaults from one card must not share it. */
    name: z.string().min(1).max(80),
    headline: z.string().min(1).max(120),
    /** What the depositor gives up. Required: a menu where every option has only
     *  upsides helps nobody choose. */
    tradeoff: z.string().min(1).max(240),
    base_asset: z.string(),
    allowed_assets: SetBound,
    permitted_venues: SetBound,
    permitted_data_sources: SetBound,
    risk_postures: z.array(z.enum(['conservative', 'balanced', 'aggressive'])).min(1),
    /** Keyed by the exact field names of Mandate.constraints. */
    constraint_ranges: z.record(z.string(), NumericRange),
    /** Rotated one per click. Uniqueness is structural, not a hope about temperature. */
    emphases: z.array(z.string()).min(3),
    persona: ArchetypePersona.optional(),
  })
  .strict()

export const ArchetypeIndex = z
  .object({
    version: z.number().int().min(1),
    archetypes: z.array(z.object({ key: z.string(), file: z.string() }).strict()).min(1),
  })
  .strict()

export type Archetype = z.infer<typeof Archetype>
export type SetBound = z.infer<typeof SetBound>
export type NumericRange = z.infer<typeof NumericRange>

// ── Describing an envelope, without a human typing a number ────────────────

const VENUE_LABELS: Record<string, string> = {
  uniswap: 'Uniswap',
  aqua: 'Aqua',
  aave: 'Aave',
  morpho: 'Morpho',
}

const label = (key: string) => VENUE_LABELS[key] ?? key

/** Oxford-comma list. Empty renders as "nothing", which is a legitimate bound. */
function list(items: readonly string[]): string {
  if (items.length === 0) return 'nothing'
  if (items.length === 1) return items[0]
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** A pinned range reads as one value, not as "30–30%". */
function span(min: string, max: string): string {
  return min === max ? min : `${min}–${max}`
}

const pct = (n: number) => `${Math.round(n * 100)}%`

/** Durations a person reads, not seconds. Chosen by magnitude rather than by a
 *  lookup table so a new bound never falls through to a raw number. */
function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const hours = seconds / 3600
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`
}

function describeSet(noun: string, bound: SetBound, pretty: (s: string) => string): string {
  const ceiling = bound.max_count ?? bound.subset_of.length
  const options = list(bound.subset_of.map(pretty))
  const required = bound.must_include.length
    ? `, always including ${list(bound.must_include.map(pretty))}`
    : ''
  if (bound.min_count === ceiling && ceiling === bound.subset_of.length) {
    return `${noun}: ${options}`
  }
  const count = span(String(bound.min_count), String(ceiling))
  return `${noun}: ${count} of ${options}${required}`
}

/**
 * The card's bound lines, generated from the envelope itself.
 *
 * Lane E renders these verbatim. Every number here came out of the same JSON
 * `check_envelope()` reads, so a card cannot advertise a bound that is not
 * enforced — which is the failure mode this replaces.
 */
export function describeEnvelope(archetype: Archetype): string[] {
  const r = archetype.constraint_ranges
  const lines = [
    describeSet('Holds', archetype.allowed_assets, (s) => s),
    describeSet('Trades on', archetype.permitted_venues, label),
  ]

  if (r.min_cash_pct) {
    lines.push(`Keeps ${span(pct(r.min_cash_pct.min), pct(r.min_cash_pct.max))} in cash`)
  }
  // Only meaningful when a non-base asset can be held; with one permitted asset
  // the cap binds on nothing and the line would state a rule that never applies.
  if (r.max_position_pct && archetype.allowed_assets.subset_of.length > 1) {
    lines.push(
      `No single position above ${span(pct(r.max_position_pct.min), pct(r.max_position_pct.max))}`,
    )
  }
  if (r.max_slippage_bps) {
    lines.push(
      `Slippage capped at ${span(String(r.max_slippage_bps.min), String(r.max_slippage_bps.max))} bps`,
    )
  }
  if (r.rebalance_cooldown_seconds) {
    const { min, max } = r.rebalance_cooldown_seconds
    lines.push(`Rebalances no more often than every ${span(duration(min), duration(max))}`)
  }
  if (r.max_actions_per_tick) {
    const { min, max } = r.max_actions_per_tick
    lines.push(`At most ${span(String(min), String(max))} actions per decision`)
  }

  lines.push(`Risk posture: ${list(archetype.risk_postures)}`)
  return lines
}

