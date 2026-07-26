import { ImageResponse } from 'next/og'

/**
 * The card a link to Scipio unfurls into, in Slack, iMessage, Discord, X and
 * anywhere else that reads Open Graph.
 *
 * Generated rather than committed as a PNG. The mark, the palette and the
 * standfirst are the same values the site itself uses, so a brand change moves
 * the preview with it instead of leaving a stale image on every link ever
 * shared — and there is no binary in the tree to keep in sync by hand.
 *
 * Drawn to the site's own rules: white canvas, ink for the statement, one blue
 * hairline as the entire accent. A social card is where the temptation to add a
 * gradient is strongest and where it would look least like this product.
 *
 * ## Constraints worth knowing before editing
 *
 * This renders through satori, not a browser. **Flexbox only** — a `div` with
 * more than one child must set `display: flex` explicitly, and there is no
 * grid, no float, no `position: static` layout. Fonts are whatever `next/og`
 * bundles, so the site's Helvetica stack is unavailable here and the design
 * leans on size, weight and spacing rather than on the typeface.
 *
 * The mark arrives as a data-URI `<img>` rather than inline SVG: satori's SVG
 * support has moved between versions and an `<img>` is the path that has not.
 */

export const alt = 'Scipio — agent curated ERC-4626 vaults'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

/** The favicon's heavier cut of the mark: a town enclosed by a wall, pressed inward. */
const MARK = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="104" height="104">
  <rect width="24" height="24" rx="4.5" fill="#005BCC"/>
  <rect x="4" y="4" width="16" height="16" fill="none" stroke="#fff" stroke-width="2"/>
  <g fill="#fff">
    <polygon points="10,5.4 14,5.4 12,8.6"/>
    <polygon points="18.6,10 18.6,14 15.4,12"/>
    <polygon points="14,18.6 10,18.6 12,15.4"/>
    <polygon points="5.4,14 5.4,10 8.6,12"/>
  </g>
  <rect x="10" y="10" width="4" height="4" fill="#fff"/>
</svg>`

/**
 * The hero's siege figure, held at the finished frame the animation lands on.
 * A card that is only type and a rule could belong to any minimal finance site;
 * this is the one drawing that says which one it is. Kept pale enough to stay
 * behind the words — the same rule the motif obeys on the page itself.
 */
const SIEGE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="380" height="380" fill="none" stroke="#005BCC">
  <rect x="140" y="140" width="120" height="120" stroke-width="4"/>
  <rect x="90" y="90" width="220" height="220" stroke-width="3"/>
  <rect x="40" y="40" width="320" height="320" stroke-width="2.4"/>
  <g fill="#005BCC" stroke="none">
    <polygon points="188,48 212,48 200,70"/>
    <polygon points="352,188 352,212 330,200"/>
    <polygon points="212,352 188,352 200,330"/>
    <polygon points="48,212 48,188 70,200"/>
    <polygon points="188,140 212,140 200,118"/>
    <polygon points="260,188 260,212 282,200"/>
    <polygon points="212,260 188,260 200,282"/>
    <polygon points="140,212 140,188 118,200"/>
  </g>
</svg>`

const MARK_URI = `data:image/svg+xml;base64,${Buffer.from(MARK).toString('base64')}`
const SIEGE_URI = `data:image/svg+xml;base64,${Buffer.from(SIEGE).toString('base64')}`

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          backgroundColor: '#FFFFFF',
          padding: '64px 80px',
          // The one structural accent, matching the rule under every section
          // heading on the site.
          borderTop: '10px solid #005BCC',
          position: 'relative',
        }}
      >
        {/* Behind the type, and clear of it: the copy column is capped at 700px
            so the figure occupies the right margin rather than sitting under a
            line of text. Placed low enough that a preview surface cropping the
            card to a square keeps the words and loses only the drawing. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={SIEGE_URI}
          width={380}
          height={380}
          alt=""
          style={{ position: 'absolute', right: 64, top: 148, opacity: 0.16 }}
        />
        {/* Wordmark */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={MARK_URI} width={88} height={88} alt="" />
          <div
            style={{
              fontSize: 64,
              fontWeight: 700,
              letterSpacing: '-0.02em',
              color: '#141A1F',
            }}
          >
            Scipio
          </div>
        </div>

        {/* The statement */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              fontSize: 58,
              fontWeight: 600,
              letterSpacing: '-0.02em',
              lineHeight: 1.1,
              color: '#141A1F',
            }}
          >
            Agent Curated Vaults
          </div>
          <div style={{ display: 'flex', width: 168, height: 3, backgroundColor: '#008CFF', marginTop: 24 }} />
          {/* Shorter than the page description on purpose. This one is set as
              art and has to hold its line count; the fuller sentence is the
              `description` in layout.tsx, which the preview prints underneath. */}
          <div
            style={{
              marginTop: 28,
              fontSize: 27,
              lineHeight: 1.45,
              color: '#5E676E',
              maxWidth: 660,
            }}
          >
            An ERC-4626 vault curated by an autonomous agent. It reads live markets and signs its
            own transactions under a mandate fixed at genesis.
          </div>
        </div>

        {/* Provenance */}
        <div
          style={{
            display: 'flex',
            fontSize: 21,
            fontWeight: 600,
            letterSpacing: '0.09em',
            color: '#939A9F',
          }}
        >
          ETHGLOBAL LISBON 2026 · BASE · SCIPIO.CAPITAL
        </div>
      </div>
    ),
    size,
  )
}
