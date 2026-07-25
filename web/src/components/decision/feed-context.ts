/**
 * Context the decision feed needs from the vault and its mandate, but which an
 * `AgentAction` does not carry.
 *
 * Threaded as one object rather than a growing list of props: both values are
 * "what the vault says", both are optional, and both are needed several levels
 * down.
 */
export type FeedContext = {
  /** symbol → decimals, from the vault's holdings. Intent amounts are unscaled without it. */
  tokenDecimals?: Record<string, number>
  /**
   * `Mandate.constraints.max_slippage_bps` — the ceiling the harness compares a
   * plan's slippage against before it will execute. Lets the feed show *why* a
   * plan was rejected rather than leaving the reader to infer it.
   */
  maxSlippageBps?: number
}
