import type { z } from 'zod'
// GenesisChatResponse is exported only as a zod schema, so it needs a value
// import to reach its inferred type; Mandate exports a type alias directly.
import { GenesisChatResponse } from '@curator/schema'
import type { Mandate as MandateT } from '@curator/schema'

type ChatMessage = { role: 'user' | 'assistant'; content: string }
type ChatResponse = z.infer<typeof GenesisChatResponse>
type MandateDraft = Partial<MandateT>

/**
 * Fixture-mode stand-in for `POST /genesis/chat`.
 *
 * This runs **only** when Lane B's API is unreachable. It exists because
 * genesis is the first thing anyone opening this app sees, and a dead chat box
 * makes the entire product look broken even when every other screen works.
 *
 * It is a scripted interviewer, not a model: it walks the four questions a
 * mandate actually needs answered — objective, risk limits, which data sources
 * the agent may consult, which venues it may use — and assembles the draft as
 * it goes. That progression *is* the genesis narrative, so it stays faithful to
 * the real flow even though the words are canned.
 *
 * Deterministic by construction: the reply depends only on the message history,
 * so the same conversation always produces the same mandate.
 */

type Available = { sources: string[]; venues: string[] }

const DEFAULT_AVAILABLE: Available = {
  sources: ['messari', 'token_api'],
  venues: ['uniswap', 'aqua'],
}

/** `permitted_venues` is a closed enum in the schema; the registry's list is not. */
function venueGrants(available: Available): Array<'uniswap' | 'aqua'> {
  const allowed = available.venues.filter(
    (venue): venue is 'uniswap' | 'aqua' => venue === 'uniswap' || venue === 'aqua',
  )
  return allowed.length > 0 ? allowed : ['uniswap', 'aqua']
}

const STAGES: Array<{
  reply: (userText: string, available: Available) => string
  draft: (
    userText: string,
    previous: Partial<MandateT>,
    available: Available,
  ) => Partial<MandateT>
}> = [
  {
    reply: () =>
      "Understood. I've started a mandate from that. Before it can be deployed I need three more things — the first is your risk limits.\n\nHow much of the vault may sit in a single non-base asset, how much cash should always stay free for redemptions, and what slippage will you tolerate on a rebalance?",
    draft: (userText) => ({
      version: 1,
      name: deriveName(userText),
      objective: userText.trim().slice(0, 2000),
      base_asset: 'USDC',
    }),
  },
  {
    reply: (_userText, available) =>
      `Recorded. Those become hard constraints I check before every action, not preferences.\n\nNext: which data sources am I permitted to consult? Registered right now: ${listPhrase(available.sources)}. I can only reason about markets I'm allowed to see, and I cannot grant myself a source later — changing this list is a mandate amendment.`,
    draft: (_userText, previous) => ({
      ...previous,
      constraints: {
        allowed_assets: ['USDC', 'WETH'],
        max_position_pct: 0.6,
        min_cash_pct: 0.2,
        max_slippage_bps: 50,
        rebalance_cooldown_seconds: 3600,
        max_actions_per_tick: 2,
        // Lane F's Wave 2 default. Allocation and exposure constraints may bend
        // by this much and be accepted with a recorded warning; slippage and
        // the allowlists never bend.
        tolerance_band_pct: 0.05,
      },
    }),
  },
  {
    reply: (_userText, available) =>
      `Granted — ${listPhrase(available.sources)}. Every fact I use will carry the source it came from, so you can audit which number drove which decision.\n\nLast question: which execution venues may I use? Uniswap lets me rotate what the vault holds; Aqua lets me hold a market-making position without the tokens ever leaving the vault.`,
    draft: (_userText, previous, available) => ({
      ...previous,
      // Whatever the registry actually has, not a baked-in list.
      permitted_data_sources:
        available.sources.length > 0 ? available.sources : DEFAULT_AVAILABLE.sources,
    }),
  },
  {
    reply: () =>
      "That completes the mandate. Review it on the right — once you deploy, it is crystallised at genesis and you cannot change it. Only I can, and only in pursuit of the objective you just gave me.\n\nDeploy when you're ready.",
    draft: (_userText, previous, available) => ({
      ...previous,
      permitted_venues: venueGrants(available),
      risk_posture: 'conservative',
      update_rules:
        'May widen allowed_assets only to assets with a Chainlink Base feed and >$50M TVL. May never reduce min_cash_pct below 0.1, and may never remove a data source that is currently the sole provider of a fact class it relies on.',
    }),
  },
]

const CLOSING_REPLY =
  'The mandate is complete and ready to deploy. If you want to change something, tell me what and I will amend the draft — after deployment that is no longer possible.'

function deriveName(userText: string): string {
  const words = userText
    .trim()
    .split(/\s+/)
    .filter((word) => /^[A-Za-z][A-Za-z-]*$/.test(word))
    .slice(0, 4)
  const candidate = words
    .map((word) => word[0].toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
    .slice(0, 80)
  return candidate.length >= 3 ? candidate : 'Base Yield Strategy'
}

/**
 * @param messages full history including the user turn just sent
 * @param previousDraft the draft accumulated so far, so stages compose
 */
export function simulateGenesisChat(
  messages: ChatMessage[],
  previousDraft: Partial<MandateT> = {},
  available: Available = DEFAULT_AVAILABLE,
): ChatResponse {
  const userTurns = messages.filter((message) => message.role === 'user')
  const stageIndex = userTurns.length - 1
  const latest = userTurns[userTurns.length - 1]?.content ?? ''

  if (stageIndex < 0) {
    return { reply: 'Tell me what you want this vault to do.' }
  }

  const stage = STAGES[stageIndex]
  if (!stage) {
    return { reply: CLOSING_REPLY, mandate_draft: previousDraft }
  }

  return {
    reply: stage.reply(latest, available),
    mandate_draft: stage.draft(latest, previousDraft, available),
  }
}

/** "messari, token_api and aave" */
function listPhrase(items: string[]): string {
  if (items.length === 0) return 'no sources are registered'
  if (items.length === 1) return items[0]
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** The opening prompt, shown before the user has said anything. */
export const GENESIS_OPENING =
  "I'll be the curator for this vault. Describe what you want it to do — the objective, and anything you would refuse to let it do. I'll turn that into a mandate you can inspect before it is deployed."

export type { ChatMessage, MandateDraft }
