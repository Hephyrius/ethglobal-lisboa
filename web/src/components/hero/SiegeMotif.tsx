/**
 * Alesia, 52 BC — the hero's background motif.
 *
 * Caesar besieged Vercingetorix inside Alesia and built *two* concentric walls:
 * a **circumvallation** facing inward at the town, and a **contravallation**
 * facing outward at the relief army coming to break the siege. The legions held
 * the ring between them, pressed from both sides at once.
 *
 * The figure draws in that order — town, then the ring around it, then the ring
 * around that; then arrowheads on the outermost perimeter pointing **in**, then
 * arrowheads on the town's own perimeter pointing **out**.
 *
 * Why it is allowed to be here at all: this is decoration on a page whose whole
 * argument is that nothing is decoration — every number on the site is read from
 * a chain. So it is drawn at very low opacity, plays once and stops, sits behind
 * the copy, is `aria-hidden`, and is dropped entirely below `lg` where the hero
 * column already fills the width. It must never compete with the type.
 *
 * `pathLength="100"` normalises every perimeter to 100 units, so one dash pair
 * animates squares of three different sizes without computing 4×side each time.
 */
export function SiegeMotif() {
  return (
    // Sized off the section rather than a fixed px value: the wrapper spans the
    // hero's height (inset-y) and the square scales to fit inside it. A fixed
    // 460px figure overflowed a 380px hero and `overflow-hidden` sliced the top
    // and bottom off the outer ring — which is the one thing this drawing cannot
    // afford, since it is entirely about closed concentric rings. Now the hero
    // can change height with the copy and the figure still fits.
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-y-6 right-0 hidden lg:block"
    >
      <svg
        viewBox="0 0 400 400"
        className="siege h-full w-auto"
        fill="none"
        stroke="currentColor"
      >
        {/* The town, then the two rings. Stroke weight falls as the rings grow:
            the innermost square is the thing under siege, so it stays the most
            present mark on the figure. */}
        <rect
          className="siege-ring siege-ring--1"
          x="140" y="140" width="120" height="120"
          pathLength="100" strokeWidth="1.6"
        />
        <rect
          className="siege-ring siege-ring--2"
          x="90" y="90" width="220" height="220"
          pathLength="100" strokeWidth="1.2"
        />
        <rect
          className="siege-ring siege-ring--3"
          x="40" y="40" width="320" height="320"
          pathLength="100" strokeWidth="1"
        />

        {/* Contravallation: on the outermost perimeter, pointing inward. */}
        <g className="siege-arrows siege-arrows--in" fill="currentColor" stroke="none">
          <polygon points="188,48 212,48 200,70" />
          <polygon points="352,188 352,212 330,200" />
          <polygon points="212,352 188,352 200,330" />
          <polygon points="48,212 48,188 70,200" />
        </g>

        {/* Circumvallation: on the town's own perimeter, pointing outward. */}
        <g className="siege-arrows siege-arrows--out" fill="currentColor" stroke="none">
          <polygon points="188,140 212,140 200,118" />
          <polygon points="260,188 260,212 282,200" />
          <polygon points="212,260 188,260 200,282" />
          <polygon points="140,212 140,188 118,200" />
        </g>
      </svg>
    </div>
  )
}
