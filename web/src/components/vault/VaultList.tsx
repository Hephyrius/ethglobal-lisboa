'use client'

import Link from 'next/link'
import { useEffect, useState, type ReactNode } from 'react'
import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { FIXTURE_VAULT_STATE } from '@/lib/api/fixtures'
import { useVaultState } from '@/lib/api/vault-queries'
import { useVaultYield } from '@/lib/api/yield-queries'
import { SHOW_SAMPLE, useKnownVaults } from '@/lib/vault/known-vaults'
import { formatAmount, formatPercent, shortAddress, shortHash } from '@/lib/format/units'
import { relativeTime } from '@/lib/format/time'

type Entry = {
  address: string
  name: string
  origin: 'local' | 'deployed' | 'onchain' | 'sample'
  createdAt?: string
  mandateHash?: string
}

/**
 * Vaults this browser knows about, from four places:
 *   - created here (localStorage — see lib/mandate/store.ts)
 *   - recorded in the deployment manifest
 *   - **everything else the factory created**, read from `vaults()` on chain
 *   - the golden fixture, so the app is explorable before anything is deployed
 *
 * The third one used to be missing, and the gap was visible in production: this
 * list read only the manifest, which records what `Deploy.s.sol` wrote. Genesis
 * and one-click archetypes both mint through the factory *without* touching
 * that file, so every vault a user actually created was invisible here while
 * appearing correctly in the explorer — which reads `useKnownVaults`. Two lists
 * of the same thing disagreeing is worse than either being wrong.
 *
 * `useKnownVaults` is now the single source, so there is one merge order and
 * one place the mandate-less deploy-script vault is filtered out.
 *
 * The sample entry is labelled as a sample. It is a way in, not a claim that a
 * vault exists.
 */
export function VaultList() {
  const [entries, setEntries] = useState<Entry[]>([])
  const { vaults, ready } = useKnownVaults()

  // Recomputed when the chain read resolves. `ready` distinguishes "no vaults"
  // from "not loaded yet", which matters because the sample entry below is
  // shown only in the first case — rendering it during the load would flash a
  // fixture at someone who owns real vaults.
  useEffect(() => {
    if (!ready) return

    const known: Entry[] = vaults.map((vault) => ({
      address: vault.address,
      name: vault.name,
      origin: vault.origin,
      createdAt: vault.createdAt,
      mandateHash: vault.mandateHash,
    }))

    // ⚠️ Never on a network holding real money — the same rule, and the same
    // reason, as the guard in `known-vaults.ts`. This is a *second* copy of the
    // placeholder, and fixing only the one in the hook left the mock address
    // still being fetched in production: `/vault/0x1111…1111/state` and
    // `/yield` against an API that has never heard of it.
    //
    // The deeper hazard is not the wasted request. A listing here renders with
    // the same card and the same deposit form as a real vault, and a visitor
    // cannot tell which is which. On a fork that is a useful way in before
    // anything is deployed; on mainnet it is a fabricated listing next to ones
    // holding actual USDC.
    const sample: Entry[] =
      !SHOW_SAMPLE || known.length > 0
        ? []
        : [
            {
              address: FIXTURE_VAULT_STATE.address,
              name: 'Conservative Base Yield',
              origin: 'sample',
              mandateHash: FIXTURE_VAULT_STATE.mandate_hash,
            },
          ]

    setEntries([...known, ...sample])
  }, [vaults, ready])

  if (entries.length === 0) {
    return (
      <Card className="border-dashed px-5 py-8 text-center">
        <p className="text-sm text-muted">No vaults yet.</p>
        <Link
          href="/create"
          className="mt-2 inline-block text-sm text-agent underline-offset-4 hover:underline"
        >
          Create one →
        </Link>
      </Card>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map((entry) => (
        <VaultCard key={entry.address} entry={entry} />
      ))}
    </div>
  )
}

/**
 * One card. Split out of the list because it holds queries of its own, and a
 * hook cannot be called inside a `.map`.
 *
 * Two live figures sit under the address: **total assets**, read with the same
 * three-rung ladder the dashboard uses, and **APY**, the forward-looking blended
 * rate on what is held right now.
 *
 * APY comes from `/vault/{addr}/yield`, **not** from the performance summary's
 * `annualized_return_pct`. That one is the realised return and is null until the
 * series spans a day, so on a vault deployed during a demo — which is every
 * vault a visitor will see — it is blank for the whole session. The yield route
 * is populated from the first tick.
 */
function VaultCard({ entry }: { entry: Entry }) {
  const stateQuery = useVaultState(entry.address)
  const yieldQuery = useVaultYield(entry.address)

  // Fixture numbers are invented, and `useVaultState` falls through to them when
  // both the API and the chain are unreachable. On the sample card that is the
  // whole point and the SAMPLE badge says so; on a real vault, printing 50,000
  // USDC because we could not read it is a financial claim about someone's
  // money. Show the shortfall instead — the same stance performance-queries.ts
  // takes when it returns an empty curve rather than a plausible one.
  const sourced = stateQuery.data
  const state =
    sourced && (sourced.mode !== 'fixture' || entry.origin === 'sample') ? sourced.data : undefined

  const apy = yieldQuery.data?.weighted_apy
  const coverage = yieldQuery.data?.coverage ?? 0

  return (
    <Link
      href={`/vault/${entry.address}`}
      className="group flex flex-col rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-bright hover:bg-raised"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="truncate text-sm font-semibold text-ink">{entry.name}</h3>
        {entry.origin === 'sample' ? (
          <Badge tone="warn">SAMPLE</Badge>
        ) : entry.origin === 'local' ? (
          <Badge tone="agent">YOURS</Badge>
        ) : (
          <Badge tone="data">DEPLOYED</Badge>
        )}
      </div>

      <div className="mt-3">
        <div className="label">Vault address</div>
        <p className="mt-1 font-mono text-xs text-muted">{shortAddress(entry.address, 6)}</p>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-3 border-t border-line pt-3">
        <CardStat
          label="Total assets"
          pending={stateQuery.isPending}
          value={
            state
              ? formatAmount(state.total_assets, state.asset_decimals, { maxFractionDigits: 2 })
              : null
          }
          sub={state ? `in ${assetSymbol(state)}` : 'vault state unavailable'}
        />
        <CardStat
          label="APY"
          // Blue is the one accent on this page and it means "the agent did
          // this". A vault sitting entirely in idle capital has honestly earned
          // 0.00%, and colouring that figure reads as an achievement.
          tone={apy != null && apy > 0 ? 'agent' : undefined}
          pending={yieldQuery.isPending}
          value={apy != null ? formatPercent(apy) : null}
          sub={
            apy == null
              ? 'no rate yet'
              : coverage >= 0.999
                ? 'blended, whole book'
                : `blended over ${Math.round(coverage * 100)}%`
          }
        />
      </div>

      <div className="mt-3 flex items-center gap-3 text-2xs text-faint">
        {entry.mandateHash ? <span>mandate {shortHash(entry.mandateHash)}</span> : null}
        {entry.createdAt ? <span>{relativeTime(entry.createdAt)}</span> : null}
      </div>
    </Link>
  )
}

/**
 * A figure on a card. `value === null` means "we could not read it", and it
 * renders as `n/a` rather than `0` — the distinction the yield route draws
 * between idle capital, which really does earn 0%, and a rate nobody knows.
 *
 * `pending` gets a skeleton rather than `n/a`, because "still loading" and
 * "unavailable" look identical once a dash is on screen and only one of them
 * is worth reloading for.
 */
function CardStat({
  label,
  value,
  sub,
  tone,
  pending,
}: {
  label: string
  value: string | null
  sub: ReactNode
  tone?: 'agent'
  pending?: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      {pending ? (
        <div className="mt-1.5 h-4 w-16 animate-pulse rounded bg-raised" />
      ) : (
        <div
          className={`tabular mt-1 truncate text-sm font-semibold ${
            value == null ? 'text-faint' : tone === 'agent' ? 'text-agent' : 'text-ink'
          }`}
        >
          {value ?? 'n/a'}
        </div>
      )}
      <div className="mt-0.5 truncate text-2xs text-faint">{sub}</div>
    </div>
  )
}

/** The base asset's symbol, taken from the holding that *is* the base asset. */
function assetSymbol(state: VaultState): string {
  const match = state.holdings.find(
    (holding) => holding.token.toLowerCase() === state.asset.toLowerCase(),
  )
  return match?.symbol ?? 'asset'
}
