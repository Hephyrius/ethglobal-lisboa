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

export function DepositWithdraw({ vault }: { vault: `0x${string}` }) {
  const { address, isConnected } = useAccount()
  const [tab, setTab] = useState<Tab>('deposit')
  const [amount, setAmount] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const position = useVaultPosition(vault, address)
  const { approve, deposit, redeem } = useVaultActions(vault, address)

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
            before the factory has deployed one. The rest of this page still renders from the agent
            API.
          </p>
          <p className="mt-2 text-2xs text-faint">
            {position.error instanceof Error ? position.error.message : null}
          </p>
        </CardBody>
      </Card>
    )
  }

  const { assetSymbol, assetDecimals, shareDecimals, walletAssets, allowance, shares, sharesInAssets, assetAddress } =
    position.data

  const decimals = tab === 'deposit' ? assetDecimals : shareDecimals
  const max = tab === 'deposit' ? walletAssets : shares

  let parsed: bigint | null = null
  try {
    parsed = amount.trim() === '' ? null : parseAmount(amount, decimals)
  } catch {
    parsed = null
  }

  const needsApproval = tab === 'deposit' && parsed !== null && allowance < parsed
  const busy = approve.isPending || deposit.isPending || redeem.isPending
  const overMax = parsed !== null && parsed > max
  const txError = approve.error ?? deposit.error ?? redeem.error

  async function submit() {
    setFormError(null)
    if (parsed === null || parsed === 0n) {
      setFormError('Enter an amount')
      return
    }
    if (overMax) {
      setFormError('Amount exceeds your balance')
      return
    }

    try {
      if (tab === 'deposit') {
        if (needsApproval) {
          await approve.mutateAsync({ token: assetAddress, amount: parsed })
        }
        await deposit.mutateAsync(parsed)
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

        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="amount" className="label">
              {tab === 'deposit' ? `Amount in ${assetSymbol}` : 'Shares to redeem'}
            </label>
            <button
              type="button"
              onClick={() => setAmount(formatAmountForInput(max, decimals))}
              className="text-2xs text-faint transition-colors hover:text-muted"
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
              'tabular mt-1.5 w-full rounded-lg border bg-canvas px-3 py-2.5 text-sm text-ink outline-none transition-colors',
              'placeholder:text-faint focus:border-agent/50',
              overMax ? 'border-bad/50' : 'border-line',
            )}
          />
        </div>

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
              : 'Redeem'}
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
