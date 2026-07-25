/**
 * The "built with" strip under the hero — a slow, looping partner marquee.
 *
 * ## The logos are the real ones, and they are vendored
 *
 * Each file in `public/logos/` came from that project's own brand channel:
 * Uniswap and The Graph from their official brand-asset archives, 1inch from
 * the mark on 1inch.io, ETHGlobal from the wordmark on ethglobal.com. See
 * `public/logos/README.md` for the exact sources.
 *
 * They are *served from this origin*, never hot-linked. That is what makes them
 * safe under the rule `ui/TokenMark.tsx` sets out: a logo host that rate-limits
 * mid-demo would leave broken-image glyphs on screen exactly when the room is
 * watching. A vendored file cannot fail that way, and unlike a mark drawn from
 * memory it cannot misrepresent the brand either.
 *
 * Each is shown in the colour its own brand pack ships, undimmed. In practice
 * that means Uniswap pink (#F50DB4) is the only real colour in the row: The
 * Graph publishes no colour variant of the full lockup, ETHGlobal's wordmark is
 * black, and 1inch's own logo file is `currentColor` — a single-ink mark by
 * design, set here to the interface ink as 1inch.io itself renders it on light
 * surfaces. Nothing is invented to even the row out.
 *
 * ## Why the keyframes are local
 *
 * They are declared in this file rather than in `globals.css` because the siege
 * motif's animation lives there and is actively being worked on. A shared file
 * is the one place two people editing in parallel actually collide, so this
 * component carries its own and is self-contained.
 */

type Partner = {
  name: string
  src: string
  /** Per-logo height. The four viewBoxes carry different amounts of padding,
   *  so a single height class leaves them optically uneven. */
  height: string
}

const PARTNERS: Partner[] = [
  { name: 'Uniswap', src: '/logos/uniswap.svg', height: 'h-5 sm:h-6' },
  { name: '1inch', src: '/logos/1inch.svg', height: 'h-4 sm:h-5' },
  { name: 'The Graph', src: '/logos/thegraph.svg', height: 'h-4 sm:h-5' },
  { name: 'ETHGlobal', src: '/logos/ethglobal.svg', height: 'h-6 sm:h-7' },
]

/**
 * How many times the row is repeated across the track.
 *
 * Two is the textbook answer and it is wrong here. Four logos with generous
 * gaps make a row roughly 650px wide, so two passes span ~1300px — barely more
 * than the 1400px content column. Once the track has scrolled past its own
 * width there is nothing queued behind it, and the strip runs out into empty
 * space before snapping back: a loop that visibly ends.
 *
 * Four passes always overflow the widest viewport this layout allows, so there
 * is unconditionally another row waiting off the right edge. The track then
 * travels exactly one row's width — `100% / COPIES` — which lands every logo
 * precisely where its predecessor was, so the reset is invisible and the motion
 * never stops.
 */
const COPIES = 4

const CSS = `
@keyframes bw-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(var(--bw-shift)); }
}
/* Duration is per row travelled, not per track, so speed holds if COPIES changes. */
.bw-track { animation: bw-scroll 30s linear infinite; will-change: transform; }
.bw-viewport:hover .bw-track { animation-play-state: paused; }

/* Motion off: the loop stops, the repeats are removed so a screenful of the
   same four logos is not what is left behind, and the row becomes scrollable
   so every partner is still reachable on a narrow viewport. */
@media (prefers-reduced-motion: reduce) {
  .bw-track { animation: none; }
  .bw-viewport { overflow-x: auto; }
  .bw-duplicate { display: none; }
}
`

export function BuiltWith() {
  return (
    <section aria-label="Built with">
      <style>{CSS}</style>

      <p className="label">Built with</p>

      {/* Only the right edge fades. With the label stacked above rather than
          beside it, the strip now starts at the page's left margin — and a
          logo dissolving there would read as a rendering fault, not as motion.
          Off the right edge, the same fade is what the logos travel into. */}
      <div
        className="bw-viewport relative mt-3 overflow-hidden"
        style={{
          maskImage: 'linear-gradient(to right, #000 calc(100% - 5rem), transparent)',
          WebkitMaskImage: 'linear-gradient(to right, #000 calc(100% - 5rem), transparent)',
        }}
      >
        <div
          className="bw-track flex w-max items-center"
          style={{ '--bw-shift': `-${100 / COPIES}%` } as React.CSSProperties}
        >
          {Array.from({ length: COPIES }, (_, i) => (
            // Only the first pass is the real list; the rest exist to keep the
            // track wider than the viewport and are hidden from assistive tech.
            <PartnerRow key={i} duplicate={i > 0} />
          ))}
        </div>
      </div>
    </section>
  )
}

function PartnerRow({ duplicate = false }: { duplicate?: boolean }) {
  return (
    <ul
      aria-hidden={duplicate || undefined}
      className={`flex shrink-0 items-center gap-10 pr-10 sm:gap-16 sm:pr-16 ${
        duplicate ? 'bw-duplicate' : ''
      }`}
    >
      {PARTNERS.map((partner) => (
        <li key={partner.name} className="shrink-0">
          {/* Plain `img`, not `next/image`: these are fixed-height vector marks
              with no variants to generate, and the optimiser's layout wrapper
              only gets in the marquee's way. The duplicate row's copies are
              decorative, so only the first pass carries alt text. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={partner.src}
            alt={duplicate ? '' : partner.name}
            aria-hidden={duplicate || undefined}
            className={`w-auto ${partner.height}`}
          />
        </li>
      ))}
    </ul>
  )
}
