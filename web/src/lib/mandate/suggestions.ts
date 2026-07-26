import type { Mandate } from '@curator/schema'
import type { ChatMessage } from '@/lib/api/genesis-sim'

/**
 * Suggested replies, so nobody faces an empty box.
 *
 * Genesis asks a reader to write an investment mandate in a vocabulary they may
 * not have, and the cost of not knowing what to type is that they leave. These
 * are one tap each and they double as a worked example of the register the
 * conversation expects — sentences about intent and limits, not commands.
 *
 * They follow the draft rather than the turn count, so a user who loaded a
 * preset gets amendments to make while a user starting cold gets openers. Once
 * the mandate is complete they stop: at that point the useful action is the
 * deploy button, and more prompts would just be noise beside it.
 */
export function suggestionsFor(messages: ChatMessage[], draft: Partial<Mandate>): string[] {
  const hasSpoken = messages.some((message) => message.role === 'user')

  // Nothing in the draft and nothing said: these have to carry the whole idea
  // of what a mandate is, so each names an objective *and* a limit.
  if (!draft.objective && !hasSpoken) {
    return [
      'Earn a steady yield on USDC with minimal drawdown. Hold no volatile assets.',
      'Hold USDC and WETH in equal weight, rebalancing on drift. Deploy the idle balance into yield.',
      'Pursue the highest risk-adjusted return available, and report whenever risk is increased.',
    ]
  }

  if (!draft.constraints) {
    return [
      'Keep at least a quarter of the book in cash, and never more than 60% in any one asset.',
      'Tolerate up to 50 bps of slippage, and do not trade more than twice per cycle.',
    ]
  }

  if (!draft.permitted_data_sources?.length) {
    return ['Grant every available data source.', 'Lending data and prices only, no sentiment.']
  }

  if (!draft.permitted_venues?.length) {
    return [
      'Uniswap and Aave. No market-making.',
      'Everything available, including Aqua market-making.',
    ]
  }

  // A complete draft: amendments a reader might not know they could ask for.
  return [
    'Raise the cash floor to 30%.',
    'Tighten the slippage ceiling to 25 bps.',
    'Explain what this mandate prohibits.',
  ]
}
