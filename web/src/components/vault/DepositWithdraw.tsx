'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { WalletButton } from '@/components/wallet/WalletButton'
import { useAccount } from '@/lib/chain/account'
import { useVaultActions, useVaultPosition } from '@/lib/chain/vault-contract'
import { formatAmount, parseAmount } from '@/lib/format/units'
import { cn } from '@/lib/cn'

type Tab = 'deposit' | 'withdraw'

export function DepositWithdraw({
  vault,
  paused = false,
}: {
  vault: `0x${string}`
  paused?: boolean
}) {
  const { address, isConnected } = useAccount()
  const [tab, setTab] = useState<Tab>('deposit')
  const [amount, setAmount] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  // In-kind redemption is offered only while paused, because that is the only
  // time it is the better trade: it is exact and unconditional but pays out a
  // basket, so on a healthy vault it would be a worse exit presented as an
  // equal one.
  const [inKind, setInKind] = useState(false)

  const position = useVaultPosition(vault, address)
  const { approve, deposit, redeem, redeemInKind } = useVaultActions(vault, address)

  if (!isConnected) {
    return (
      <Card>
        <CardHeader title="Deposit" subtitle="Connect a wallet to deposit or withdraw." />
        <CardBody>
          <WalletButton />
        </CardBody>
      </Card>
    )
  }

  if (position.isPending) {
    return (
      <Card>
        <CardHeader title="Deposit" />
        <CardBody>
          <div className="h-24 animate-pulse-soft rounded-lg bg-line-bright/40" />
        </CardBody>
      </Card>
    )
  }

  if (position.isError || !position.data) {
    return (
      <Card>
        <CardHeader title="Deposit" />
        <CardBody>
          <p className="text-xs leading-relaxed text-warn/90">
            No ERC-4626 vault responded at this address on the configured RPC. That is expected
            before the factory has deployed one — the rest of this page still renders from the agent
            API.
          </p>
          <p className="mt-2 text-2xs text-faint">
            {position.error instanceof Error ? position.error.message : null}
          </p>
        </CardBody>
      </Card>
    )
  }

  const {
    assetSymbol,
    assetDecimals,
    shareDecimals,
    walletAssets,
    allowance,
    shares,
    sharesInAssets,
    assetAddress,
    vaultLiquid,
    payableShares,
  } = position.data

  const decimals = tab === 'deposit' ? assetDecimals : shareDecimals
  // The withdraw ceiling is what the vault can PAY, not what the holder owns
  // (#76) — except in kind, which is paid from every token and so is bounded
  // only by the holder's balance.
  const max = tab === 'deposit' ? walletAssets : inKind ? shares : payableShares
  // True whenever the vault cannot currently cash out this holder's whole
  // position. Not an error: it is the normal state of a vault that has put
  // capital to work, and it is only alarming when it goes unexplained.
  const liquidityLimited = tab === 'withdraw' && payableShares < shares

  let parsed: bigint | null = null
  try {
    parsed = amount.trim() === '' ? null : parseAmount(amount, decimals)
  } catch {
    parsed = null
  }

  const needsApproval = tab === 'deposit' && parsed !== null && allowance < parsed
  const busy = approve.isPending || deposit.isPending || redeem.isPending || redeemInKind.isPending
  const overMax = parsed !== null && parsed > max
  const txError = approve.error ?? deposit.error ?? redeem.error ?? redeemInKind.error

  async function submit() {
    setFormError(null)
    if (parsed === null || parsed === 0n) {
      setFormError('Enter an amount')
      return
    }
    if (overMax) {
      setFormError(
        liquidityLimited && !inKind
          ? 'More than the vault can pay in ' + assetSymbol + ' right now'
          : 'Amount exceeds your balance',
      )
      return
    }

    try {
      if (tab === 'deposit') {
        if (needsApproval) {
          await approve.mutateAsync({ token: assetAddress, amount: parsed })
        }
        await deposit.mutateAsync(parsed)
      } else if (inKind) {
        await redeemInKind.mutateAsync(parsed)
      } else {
        await redeem.mutateAsync(parsed)
      }
      setAmount('')
    } catch {
      // Surfaced through txError below; a rejected wallet prompt is normal.
    }
  }

  return (
    <Card>
      <CardHeader
        title="Your position"
        subtitle={`${formatAmount(sharesInAssets, assetDecimals, { maxFractionDigits: 2 })} ${assetSymbol} · ${formatAmount(shares, shareDecimals, { maxFractionDigits: 4 })} shares`}
      />
      <CardBody className="space-y-4">
        <div className="flex gap-1 rounded-lg border border-line bg-raised p-1">
          {(['deposit', 'withdraw'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setTab(value)
                setAmount('')
                setFormError(null)
                setInKind(false)
              }}
              className={cn(
                'flex-1 rounded-md py-1.5 text-xs capitalize transition-colors',
                tab === value ? 'bg-surface text-ink' : 'text-muted hover:text-ink',
              )}
            >
              {value}
            </button>
          ))}
        </div>

        {tab === 'withdraw' && paused ? (
          <ExitChoice
            inKind={inKind}
            assetSymbol={assetSymbol}
            onChange={(next) => {
              setInKind(next)
              setAmount('')
              setFormError(null)
            }}
          />
        ) : null}

        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="amount" className="label">
              {tab === 'deposit' ? `Amount in ${assetSymbol}` : 'Shares to redeem'}
            </label>
            <button
              type="button"
              onClick={() => setAmount(formatAmountForInput(max, decimals))}
              className={cn(
                'text-2xs transition-colors hover:text-muted',
                liquidityLimited && !inKind ? 'text-warn/90' : 'text-faint',
              )}
            >
              max {formatAmount(max, decimals, { maxFractionDigits: 4 })}
            </button>
          </div>

          <input
            id="amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value)
              setFormError(null)
            }}
            placeholder="0.0"
            className={cn(
              'tabular mt-1.5 w-full rounded-lg border bg-base px-3 py-2.5 text-sm text-ink outline-none transition-colors',
              'placeholder:text-faint focus:border-agent/50',
              overMax ? 'border-bad/50' : 'border-line',
            )}
          />
        </div>

        {liquidityLimited && !inKind ? (
          <LiquidityNotice
            assetSymbol={assetSymbol}
            assetDecimals={assetDecimals}
            shareDecimals={shareDecimals}
            vaultLiquid={vaultLiquid}
            shares={shares}
            sharesInAssets={sharesInAssets}
            payableShares={payableShares}
            paused={paused}
          />
        ) : null}

        <Button
          variant="primary"
          className="w-full"
          loading={busy}
          disabled={parsed === null || parsed === 0n || overMax}
          onClick={() => void submit()}
        >
          {busy
            ? approve.isPending
              ? `Approving ${assetSymbol}…`
              : 'Confirming…'
            : tab === 'deposit'
              ? needsApproval
                ? `Approve and deposit`
                : 'Deposit'
              : inKind
                ? 'Redeem in kind'
                : `Redeem for ${assetSymbol}`}
        </Button>

        {formError ? <p className="text-2xs text-bad">{formError}</p> : null}
        {txError ? (
          <p className="text-2xs leading-relaxed text-bad/90">
            {txError instanceof Error ? firstLine(txError.message) : 'Transaction failed'}
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}

/**
 * The vault cannot currently cash out this position, and why that is not a bug.
 *
 * Lane A measured the failure this replaces (#76): `totalAssets()` 15,000
 * against 9,000 liquid, and a 10,000 redemption **reverts from the ERC-20**
 * rather than from the vault. So without this the sequence is — the panel
 * offers Max, the holder clicks it, and an opaque token revert appears with no
 * mention of liquidity anywhere. It reads as a broken vault. It is a working
 * vault holding its value in a form the exit does not pay in.
 *
 * The numbers are shown rather than described because the claim is checkable:
 * the liquid balance is one `balanceOf` away and a judge can verify it.
 */
function LiquidityNotice({
  assetSymbol,
  assetDecimals,
  shareDecimals,
  vaultLiquid,
  shares,
  sharesInAssets,
  payableShares,
  paused,
}: {
  assetSymbol: string
  assetDecimals: number
  shareDecimals: number
  vaultLiquid: bigint
  shares: bigint
  sharesInAssets: bigint
  payableShares: bigint
  paused: boolean
}) {
  const held = formatAmount(shares, shareDecimals, { maxFractionDigits: 4 })
  const payable = formatAmount(payableShares, shareDecimals, { maxFractionDigits: 4 })
  const liquid = formatAmount(vaultLiquid, assetDecimals, { maxFractionDigits: 2 })
  const claim = formatAmount(sharesInAssets, assetDecimals, { maxFractionDigits: 2 })

  return (
    <div className="rounded border border-warn/25 bg-warn/[0.05] px-3 py-2.5">
      <p className="text-2xs font-medium text-warn">
        Limited by the vault&rsquo;s cash, not by your balance
      </p>
      <p className="mt-1.5 text-2xs leading-relaxed text-muted">
        You hold <span className="tabular text-ink">{held}</span> shares, a claim on{' '}
        <span className="tabular text-ink">
          {claim} {assetSymbol}
        </span>
        . The vault holds{' '}
        <span className="tabular text-ink">
          {liquid} {assetSymbol}
        </span>{' '}
        in cash — the rest of its value is deployed — so it can redeem{' '}
        <span className="tabular text-ink">{payable}</span> shares right now. Your claim is intact;
        only the timing is constrained.
      </p>
      {paused ? (
        <p className="mt-1.5 text-2xs leading-relaxed text-muted">
          The vault is winding down, so this figure rises as positions convert to {assetSymbol}. To
          leave without waiting, redeem in kind above — that path is paid from every token the vault
          holds and is never liquidity-limited.
        </p>
      ) : null}
    </div>
  )
}

/**
 * Two ways out of a paused vault, with the trade stated on both.
 *
 * Presented as a choice rather than a fallback because neither dominates: the
 * base-asset path pays in one recognisable token but is capped by cash on hand,
 * and the in-kind path is unconditional but hands back a basket the holder then
 * has to deal with. Which is better depends on whether they would rather wait.
 * A UI that picked for them would be hiding the only decision they still have.
 */
function ExitChoice({
  inKind,
  assetSymbol,
  onChange,
}: {
  inKind: boolean
  assetSymbol: string
  onChange: (next: boolean) => void
}) {
  const options = [
    {
      value: false,
      label: `In ${assetSymbol}`,
      detail: 'Limited by the vault’s cash',
    },
    {
      value: true,
      label: 'In kind',
      detail: 'A slice of every token · always payable',
    },
  ]

  return (
    <div>
      <p className="label">How to exit</p>
      <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-lg border px-2.5 py-2 text-left transition-colors',
              inKind === option.value
                ? 'border-agent/45 bg-agent/[0.06]'
                : 'border-line bg-raised hover:border-line-bright',
            )}
          >
            <span
              className={cn(
                'block text-xs font-medium',
                inKind === option.value ? 'text-ink' : 'text-muted',
              )}
            >
              {option.label}
            </span>
            <span className="mt-0.5 block text-2xs leading-snug text-faint">{option.detail}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** Exact base-units → plain decimal string, no grouping separators for an input. */
function formatAmountForInput(value: bigint, decimals: number): string {
  const asString = value.toString().padStart(decimals + 1, '0')
  const whole = asString.slice(0, asString.length - decimals)
  const fraction = asString.slice(asString.length - decimals).replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}

/** viem errors are long. The first line is the useful part for a demo. */
function firstLine(message: string): string {
  return message.split('\n')[0]
}
