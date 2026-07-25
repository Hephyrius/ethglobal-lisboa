'use client'

import { useId, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'

/**
 * A share-price curve, drawn as inline SVG.
 *
 * ## Why this is hand-rolled rather than a charting library
 *
 * The JS dependency policy requires packages roughly six months old and exactly
 * pinned, audited against the whole lockfile. Adding recharts or visx the night
 * before submission is precisely the supply-chain risk that policy exists to
 * prevent — and it would pull in twenty transitive packages to draw one
 * polyline. This is ~150 lines with no dependency and no bundle cost.
 *
 * ## Two things it deliberately does not do
 *
 * **No smoothing.** The series is event-spaced: on a pinned fork a block is
 * mined only when a transaction lands, so a flat stretch between two trades is
 * the truth. A spline through those points would invent intermediate prices
 * that the vault never had.
 *
 * **No zero baseline.** A share price sits near 1.0 and moves in basis points;
 * anchoring the y-axis at zero renders every vault as a flat line. The domain
 * is the observed range with a small pad, and the *starting* value is drawn as
 * a reference rule so gain and loss are still visible at a glance.
 */

export type ChartPoint = {
  /** Milliseconds since epoch. */
  t: number
  /** Value in whatever unit the caller formats. */
  v: number
  /** Optional marker — an executed decision, rendered as a dot. */
  marker?: { id: string; label: string }
}

const VIEW_W = 800
const VIEW_H = 220
const PAD_L = 8
const PAD_R = 8
const PAD_T = 12
const PAD_B = 18

export function LineChart({
  points,
  formatValue,
  formatTime,
  onMarkerClick,
  className,
  ariaLabel,
}: {
  points: ChartPoint[]
  formatValue: (value: number) => string
  formatTime: (ms: number) => string
  onMarkerClick?: (id: string) => void
  className?: string
  ariaLabel: string
}) {
  const gradientId = useId()
  const [hover, setHover] = useState<number | null>(null)

  const geometry = useMemo(() => build(points), [points])

  if (!geometry) {
    return (
      <div
        className={cn(
          'flex h-[220px] items-center justify-center rounded border border-dashed border-line text-xs text-faint',
          className,
        )}
      >
        Not enough history to draw a curve yet.
      </div>
    )
  }

  const { xs, ys, path, area, first, last, min, max, rising } = geometry
  const stroke = rising ? 'var(--chart-up, #0F7A43)' : 'var(--chart-down, #CC0000)'
  const active = hover === null ? null : points[hover]

  return (
    <figure className={cn('relative', className)}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="h-[220px] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect()
          const ratio = (event.clientX - box.left) / box.width
          setHover(nearest(xs, PAD_L + ratio * (VIEW_W - PAD_L - PAD_R)))
        }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.14" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* The starting value, not zero. Everything above this line is gain. */}
        <line
          x1={PAD_L}
          x2={VIEW_W - PAD_R}
          y1={ys[0]}
          y2={ys[0]}
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="3 4"
          className="text-line-bright"
          vectorEffect="non-scaling-stroke"
        />

        <path d={area} fill={`url(#${gradientId})`} />
        <path
          d={path}
          fill="none"
          stroke={stroke}
          strokeWidth="1.75"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {points.map((point, index) =>
          point.marker ? (
            <circle
              key={point.marker.id}
              cx={xs[index]}
              cy={ys[index]}
              r="4"
              className="cursor-pointer fill-surface stroke-agent"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
              onClick={() => onMarkerClick?.(point.marker!.id)}
            >
              <title>{point.marker.label}</title>
            </circle>
          ) : null,
        )}

        {active && hover !== null ? (
          <>
            <line
              x1={xs[hover]}
              x2={xs[hover]}
              y1={PAD_T}
              y2={VIEW_H - PAD_B}
              stroke="currentColor"
              strokeWidth="1"
              className="text-line-bright"
              vectorEffect="non-scaling-stroke"
            />
            <circle cx={xs[hover]} cy={ys[hover]} r="3" fill={stroke} />
          </>
        ) : null}
      </svg>

      {/* Axis labels sit outside the SVG so `preserveAspectRatio="none"` cannot
          stretch the type — the reason the chart itself carries no <text>. */}
      <div className="mt-1 flex justify-between text-2xs tabular text-faint">
        <span>{formatTime(first.t)}</span>
        <span>
          {formatValue(min)} – {formatValue(max)}
        </span>
        <span>{formatTime(last.t)}</span>
      </div>

      {active ? (
        <figcaption className="pointer-events-none absolute -top-1 right-0 rounded border border-line bg-surface px-2 py-1 text-2xs tabular shadow-sm">
          <span className="font-semibold text-ink">{formatValue(active.v)}</span>
          <span className="ml-2 text-faint">{formatTime(active.t)}</span>
        </figcaption>
      ) : null}
    </figure>
  )
}

/** Screen coordinates for the series, or null when there is nothing to draw. */
function build(points: ChartPoint[]) {
  if (points.length < 2) return null

  const times = points.map((p) => p.t)
  const values = points.map((p) => p.v)
  const tMin = Math.min(...times)
  const tMax = Math.max(...times)
  const vMin = Math.min(...values)
  const vMax = Math.max(...values)

  // A vault that has not moved is a horizontal line, not a division by zero.
  const vSpan = vMax - vMin || Math.max(Math.abs(vMax) * 1e-4, 1e-9)
  const tSpan = tMax - tMin || 1
  const pad = vSpan * 0.12

  const x = (t: number) => PAD_L + ((t - tMin) / tSpan) * (VIEW_W - PAD_L - PAD_R)
  const y = (v: number) =>
    VIEW_H - PAD_B - ((v - (vMin - pad)) / (vSpan + pad * 2)) * (VIEW_H - PAD_T - PAD_B)

  const xs = times.map(x)
  const ys = values.map(y)

  const path = xs.map((cx, i) => `${i === 0 ? 'M' : 'L'}${cx.toFixed(2)} ${ys[i].toFixed(2)}`).join(' ')
  const area = `${path} L${xs[xs.length - 1].toFixed(2)} ${VIEW_H - PAD_B} L${xs[0].toFixed(2)} ${VIEW_H - PAD_B} Z`

  return {
    xs,
    ys,
    path,
    area,
    first: points[0],
    last: points[points.length - 1],
    min: vMin,
    max: vMax,
    rising: values[values.length - 1] >= values[0],
  }
}

function nearest(xs: number[], target: number): number {
  let best = 0
  let bestDistance = Infinity
  for (let i = 0; i < xs.length; i += 1) {
    const distance = Math.abs(xs[i] - target)
    if (distance < bestDistance) {
      bestDistance = distance
      best = i
    }
  }
  return best
}
