'use client'

import { Badge } from '@/components/ui/Badge'
import { TokenMark } from '@/components/ui/TokenMark'
import { KNOWN_TOKENS } from '@/lib/chain/deployments'
import { MANDATE_PRESETS } from '@/lib/mandate/presets'

/**
 * Which tokens a vault may hold.
 *
 * ## Where the list comes from
 *
 * There is no asset registry to read. `GET /genesis/sources` serves sources and
 * venues only, so unlike `UniverseStrip` this cannot be driven by an endpoint.
 * What it can be driven by is the two places that do record assets factually:
 * `deployments/base-fork.json`, whose `external` block is the set Lane A has
 * actually deployed against, and the `allowed_assets` the shipped presets name.
 * Nothing below is a symbol typed out by hand.
 *
 * ## Why unusable assets are listed rather than hidden
 *
 * The same reason `VenueStrip` shows unavailable venues instead of filtering
 * them: silence is how a fully-built Aave venue stayed invisible for an entire
 * wave, because an omission looks exactly like the feature not existing. The
 * LSTs are the live case. They are real assets on Base that this project has
 * deliberately not enabled, and the reason is specific rather than "not done
 * yet" — the vault values holdings by reading one Chainlink feed per token and
 * cannot compose two, so an ETH-quoted feed cannot be converted into the USD
 * terms `totalAssets()` reports. A reader who does not see them at all learns
 * nothing; a reader who sees them with the constraint attached learns where the
 * edge of the system is.
 */

type PendingAsset = { symbol: string; reason: string }

/** Assets the vault can hold today, from the deploy record and the presets. */
const AVAILABLE: string[] = (() => {
  const seen = new Set<string>()
  for (const [symbol, address] of Object.entries(KNOWN_TOKENS)) {
    if (address) seen.add(symbol)
  }
  for (const preset of MANDATE_PRESETS) {
    seen.add(preset.mandate.base_asset)
    for (const asset of preset.mandate.constraints.allowed_assets ?? []) seen.add(asset)
  }
  return [...seen]
})()

/**
 * Real assets on Base that a vault cannot hold yet, each with the actual
 * blocker. Kept short on purpose: an aspirational roadmap in a product surface
 * is a promise, and this is a list of constraints instead.
 */
const PENDING: PendingAsset[] = [
  {
    symbol: 'cbETH',
    reason:
      'Its Chainlink feed on Base is quoted in ETH, not USD. The vault reads one feed per token and cannot compose two, and the feed is fixed when the vault is initialised.',
  },
  {
    symbol: 'wstETH',
    reason:
      'Same constraint as cbETH: an ETH-quoted feed that the vault cannot convert into the USD terms it reports holdings in.',
  },
]

const NOTES: Record<string, string> = {
  USDC: 'Dollar stablecoin. The usual base asset, and what a cash floor is held in.',
  WETH: 'Wrapped ether. The main volatile leg on Base.',
  USDT: 'Dollar stablecoin.',
  DAI: 'Dollar stablecoin, collateral backed.',
  cbBTC: 'Coinbase wrapped bitcoin. The BTC leg, priced by its own Chainlink feed.',
  AERO: "Aerodrome's token, the main DEX on Base. The most volatile thing here.",
  // The receipt tokens are the ones a reader is most likely to mistake for a
  // separate exposure, so both say plainly what they are a claim on.
  aBasUSDC:
    'Aave receipt for supplied USDC — not a second exposure. A 1:1 claim, valued by the USDC feed, and what earns the lending yield.',
  aBasWETH: 'Aave receipt for supplied WETH. Same 1:1 claim, valued by the ETH feed.',
  gtUSDCp:
    'Gauntlet USDC Prime, an ERC-4626 share. Valued by composing its share price with the USDC feed rather than by a feed of its own.',
}

/**
 * Case-folded once here rather than at each lookup. The keys above are written
 * the way the tokens spell themselves — `cbBTC`, `aBasUSDC`, `gtUSDCp` — and a
 * bare `NOTES[symbol.toUpperCase()]` silently misses every one of them, so the
 * mixed-case assets rendered as bare symbols with no explanation. Only the
 * already-uppercase entries worked, which is exactly the kind of half-working
 * that survives review.
 */
const NOTE_BY_SYMBOL = new Map(Object.entries(NOTES).map(([k, v]) => [k.toUpperCase(), v]))

export function AssetUniverse() {
  if (AVAILABLE.length === 0) return null

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
        <h2 className="text-sm font-semibold text-ink">Asset universe</h2>
        <span className="text-2xs text-faint">{AVAILABLE.length} available</span>
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-faint">
        Which tokens the vault is allowed to hold. Name the ones you want in the conversation. The
        base asset is what deposits and the cash floor are denominated in, and everything else is a
        position the agent may take.
      </p>

      <ul className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {AVAILABLE.map((symbol) => (
          <li key={symbol} className="rounded border border-line bg-surface p-3">
            <div className="flex flex-wrap items-center gap-2">
              <TokenMark symbol={symbol} size="md" />
              <span className="text-sm font-medium text-ink">{symbol}</span>
            </div>
            {NOTE_BY_SYMBOL.get(symbol.toUpperCase()) ? (
              <p className="mt-2 text-2xs leading-relaxed text-muted">
                {NOTE_BY_SYMBOL.get(symbol.toUpperCase())}
              </p>
            ) : null}
          </li>
        ))}

        {PENDING.map((asset) => (
          <li
            key={asset.symbol}
            className="rounded border border-warn/30 bg-warn/[0.04] p-3 opacity-90"
          >
            <div className="flex flex-wrap items-center gap-2">
              <TokenMark symbol={asset.symbol} size="md" />
              <span className="text-sm font-medium text-ink">{asset.symbol}</span>
              <Badge tone="warn">not yet holdable</Badge>
            </div>
            <p className="mt-2 text-2xs leading-relaxed text-warn/90">{asset.reason}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
