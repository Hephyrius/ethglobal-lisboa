import { cn } from '@/lib/cn'

/**
 * The Scipio mark — the hero's Alesia figure, reduced to a logo.
 *
 * Same idea as `SiegeMotif`: a town enclosed by a wall, pressed inward. It is
 * *not* the same drawing. The hero figure carries three concentric rings and
 * eight arrowheads, which at 24px collapses into grey mush — three strokes
 * inside 24 pixels leaves under 3px between them, and an arrowhead scaled to
 * match would be a single grey pixel.
 *
 * So the mark keeps only what survives the size: one wall, four heads pressing
 * in at the midpoints, and a solid centre for the town. That is the whole
 * argument of the figure — enclosure and pressure — at the smallest size it
 * still reads at.
 *
 * Drawn on the 24px grid rather than scaled down from the hero's 400-unit
 * viewBox, so the strokes land on whole pixels instead of straddling them.
 */
export function ScipioMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-agent',
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden="true">
        {/* The wall. Inset so the rounded tile does not clip its corners. */}
        <rect
          x="4.4" y="4.4" width="15.2" height="15.2"
          fill="none" stroke="white" strokeWidth="1.3" strokeOpacity="0.95"
        />
        {/* Four heads on the wall's midpoints, pointing in. */}
        <g fill="white">
          <polygon points="10.6,5.6 13.4,5.6 12,7.9" />
          <polygon points="18.4,10.6 18.4,13.4 16.1,12" />
          <polygon points="13.4,18.4 10.6,18.4 12,16.1" />
          <polygon points="5.6,13.4 5.6,10.6 7.9,12" />
        </g>
        {/* The town. */}
        <rect x="10.4" y="10.4" width="3.2" height="3.2" fill="white" />
      </svg>
    </span>
  )
}
