import { cn } from '@/lib/cn'

/**
 * A token's mark, drawn inline.
 *
 * ## Why nothing is fetched
 *
 * Hot-linking a logo CDN or a token list means a demo that renders broken
 * images the moment that host rate-limits — a worse outcome than no logos at
 * all, and a failure that lands exactly when the room is watching. Every mark
 * here is inline SVG or a monogram: no network, no bundle weight, no broken
 * image glyph, and it scales to any size cleanly.
 *
 * ## Why most are monograms rather than brand logos
 *
 * ETH's diamond is plain geometry and safe to draw. The rest are lettered
 * chips in a per-token colour, which is the *documented fallback* — "a missing
 * logo should degrade to a clean monogram, not a broken-image glyph" — applied
 * uniformly rather than half the row being brand art and half not. In a
 * restrained, serif, trad-fi interface a consistent set of lettered chips reads
 * better than a partial set of logos, and it cannot misrepresent a brand by
 * approximating its mark badly.
 *
 * An unknown token still gets a mark: its initial on a neutral chip. Nothing
 * ever renders empty.
 */

const COLOURS: Record<string, string> = {
  USDC: '#2775CA',
  USDT: '#26A17B',
  DAI: '#F5AC37',
  WETH: '#454A75',
  ETH: '#454A75',
  WSTETH: '#00A3FF',
  CBETH: '#0052FF',
  AAVE: '#B6509E',
  MORPHO: '#2470FF',
}

const SIZES = {
  sm: 'h-4 w-4 text-[8px]',
  md: 'h-5 w-5 text-[9px]',
} as const

export function TokenMark({
  symbol,
  size = 'sm',
  className,
}: {
  symbol: string
  size?: keyof typeof SIZES
  className?: string
}) {
  const key = symbol.toUpperCase()
  const colour = COLOURS[key] ?? '#5B646F'

  if (key === 'WETH' || key === 'ETH') {
    return (
      <span
        title={symbol}
        className={cn(
          'inline-flex shrink-0 items-center justify-center rounded-full',
          SIZES[size],
          className,
        )}
        style={{ background: colour }}
      >
        <EthereumDiamond />
      </span>
    )
  }

  // The first two characters read better than one for tickers like `cbETH`,
  // and better than three, which stops looking like a mark and starts looking
  // like truncated text.
  const monogram = key.replace(/^W/, '').slice(0, 2)

  return (
    <span
      title={symbol}
      aria-hidden
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold leading-none text-white',
        SIZES[size],
        className,
      )}
      style={{ background: colour }}
    >
      {monogram}
    </span>
  )
}

/** Geometry, not brand art — the octahedron every Ethereum mark is built on. */
function EthereumDiamond() {
  return (
    <svg viewBox="0 0 12 18" className="h-[70%] w-auto" aria-hidden focusable="false">
      <path d="M6 0 0 9.2 6 12.6 12 9.2Z" fill="#fff" fillOpacity="0.95" />
      <path d="M6 13.8 0 10.4 6 18l6-7.6Z" fill="#fff" fillOpacity="0.7" />
    </svg>
  )
}
