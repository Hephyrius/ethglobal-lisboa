import { formatUnits, parseUnits } from 'viem'

/**
 * Every uint256 crosses the boundary as a decimal string, never a JSON number
 * (packages/schema/README.md). `Number("49875000000000000000000")` silently
 * loses precision — it is above Number.MAX_SAFE_INTEGER — so nothing in this
 * app may parse a balance with Number(). Everything routes through here, where
 * the input stays a string and the arithmetic stays bigint.
 *
 * This module is deliberately the only place that converts a chain amount into
 * something a human reads.
 */

/** Share price and other 1e18 fixed-point ratios from the API. */
export const RATIO_DECIMALS = 18

export function toBigInt(value: string | bigint | undefined | null): bigint {
  if (typeof value === 'bigint') return value
  if (!value) return 0n
  try {
    return BigInt(value)
  } catch {
    return 0n
  }
}

export function isZero(value: string | bigint | undefined | null): boolean {
  return toBigInt(value) === 0n
}

type AmountOptions = {
  /** Significant fraction digits to show. Defaults scale with magnitude. */
  maxFractionDigits?: number
  /** Render 1_234_567 as "1.23M". Off by default — exactness beats brevity for balances. */
  compact?: boolean
}

/**
 * Raw base-unit string → grouped human string.
 * `formatAmount("35000000000", 6)` → `"35,000.00"`
 */
export function formatAmount(
  raw: string | bigint | undefined | null,
  decimals: number,
  options: AmountOptions = {},
): string {
  const asDecimalString = formatUnits(toBigInt(raw), decimals)
  // formatUnits already gave us an exact decimal string. Number() here is safe
  // *only* because we are formatting for display after the scaling divide, and
  // the magnitude is now human-scale. Never do this before the divide.
  const n = Number(asDecimalString)
  if (!Number.isFinite(n)) return asDecimalString

  const maxFractionDigits =
    options.maxFractionDigits ?? (Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : 6)

  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: Math.min(2, maxFractionDigits),
    maximumFractionDigits: maxFractionDigits,
    notation: options.compact ? 'compact' : 'standard',
  }).format(n)
}

/** Base-unit string → JS number, for charting/relative sizing only. Never for money math. */
export function toDisplayNumber(raw: string | bigint | undefined | null, decimals: number): number {
  const n = Number(formatUnits(toBigInt(raw), decimals))
  return Number.isFinite(n) ? n : 0
}

/** Human input ("1250.5") → base units, for building a transaction. Throws on garbage. */
export function parseAmount(input: string, decimals: number): bigint {
  const cleaned = input.trim().replace(/,/g, '')
  if (!/^\d*\.?\d*$/.test(cleaned) || cleaned === '' || cleaned === '.') {
    throw new Error('Enter a number')
  }
  return parseUnits(cleaned, decimals)
}

/** 1e18 fixed-point ratio string → "1.0025". */
export function formatRatio(raw: string | bigint | undefined | null, fractionDigits = 4): string {
  return formatAmount(raw, RATIO_DECIMALS, { maxFractionDigits: fractionDigits })
}

/** 0.0432 → "4.32%". Fact APYs are fractions (schema invariant). */
export function formatPercent(fraction: number, fractionDigits = 2): string {
  return `${(fraction * 100).toFixed(fractionDigits)}%`
}

/** 84200000 → "$84.2M". For Fact values, which are plain JSON numbers. */
export function formatUsd(value: number, options: { compact?: boolean } = {}): string {
  const compact = options.compact ?? Math.abs(value) >= 100_000
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : 2,
  }).format(value)
}

/** Truncate an address for display: 0x8335…2913 */
export function shortAddress(address: string | undefined | null, size = 4): string {
  if (!address || address.length < 2 * size + 2) return address ?? ''
  return `${address.slice(0, 2 + size)}…${address.slice(-size)}`
}

/** Truncate a 32-byte hash a little longer than an address — they get compared visually. */
export function shortHash(hash: string | undefined | null): string {
  return shortAddress(hash, 6)
}
