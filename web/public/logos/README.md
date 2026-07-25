# Partner logos

Used by the "Built with" strip on the landing page
(`src/components/layout/BuiltWith.tsx`).

## Why these are vendored rather than hot-linked

`ui/TokenMark.tsx` sets the rule: nothing in this UI fetches art from a logo
host, because a host that rate-limits mid-demo leaves broken-image glyphs on
screen at the worst possible moment. Serving these from our own origin keeps
the strip working offline and on a dead network. It is also why they are not
hand-drawn approximations — an inaccurate mark misrepresents a brand more
visibly than no mark at all.

## Sources

Each file came from that project's own brand channel, retrieved 2026-07-26.

| File | Source | Original | Colour |
|---|---|---|---|
| `uniswap.svg` | `github.com/Uniswap/brand-assets` → `Uniswap Brand Assets.zip` | `Uniswap_horizontallogo_pink.svg` | `#F50DB4` as shipped |
| `1inch.svg` | `1inch.io` | `assets/images/logo.svg` | see note |
| `thegraph.svg` | `thegraph.com/brand` → `The Graph - Brand assets.zip` | `Logos/Logo/The Graph - Logo - Dark.svg` | `#0C0A1D` as shipped |
| `ethglobal.svg` | `ethglobal.com` | inline header wordmark | black |

Each is the colour variant its own brand pack ships. Only Uniswap is actually
chromatic, and that is not an oversight:

- **The Graph** publishes no colour version of the full lockup — `Dark` and
  `Light` only. Its violet `#6F4CFF` exists solely on the standalone GRT
  symbol, which is a different mark from the logo.
- **1inch** ships its logo as `fill="currentColor"`: a single-ink mark by
  design, with no brand colour to preserve. Set to the interface ink `#141A1F`,
  which is how 1inch.io renders it on light surfaces.
- **ETHGlobal**'s wordmark is black.

## What was modified

Geometry and colour are untouched, except where noted above. For each file:

- intrinsic `width`/`height` dropped so CSS height alone drives size —
  `viewBox` is preserved, so nothing is distorted
- XML prologue and comments stripped
- `ethglobal.svg` only: the root carried `fill="none"` from its Figma export,
  and its paths have no fill of their own — so detached from the page CSS that
  coloured it, the whole wordmark renders invisible. Root set to `#000000`.

## Trademarks

These marks are the trademarks of their respective owners and appear here as
attribution — the hackathon sponsors and protocols this project is built on.
They do not imply endorsement.
