# Brand assets — ETHGlobal submission

| File | Size | Where it goes |
|---|---|---|
| `scipio-logo-512.png` | 512×512 | Submission **Logo** field (square icon) |
| `scipio-cover-640x360.png` | 640×360 (16:9) | Submission **Cover image** field |
| `scipio-built-with-1200x200.png` | 1200×200 | Partner strip — READMEs, slides, anywhere it cannot animate |
| `scipio-built-with@2x.png` | 2400×400 | The same strip for retina / print |

All are generated from the sources beside them, so they can be regenerated
rather than re-drawn:

```sh
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --screenshot=scipio-logo-512.png --window-size=512,512 file://"$PWD"/logo.html
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --screenshot=scipio-cover-640x360.png --window-size=640,360 file://"$PWD"/cover.html

# The partner strip inlines the four vendored marks, so it is built first.
python3 build-strip.py strip.html
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --screenshot=scipio-built-with-1200x200.png --window-size=1200,200 file://"$PWD"/strip.html
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --screenshot=scipio-built-with@2x.png --window-size=1200,200 file://"$PWD"/strip.html
```

## Why they look like this

**Nothing here is a new identity.** The logo is the geometry already shipped in
[`web/src/app/icon.svg`](../../web/src/app/icon.svg) and
[`ScipioMark.tsx`](../../web/src/components/brand/ScipioMark.tsx) — a town enclosed
by a wall, four heads pressing in at the midpoints — so the submission card, the
browser tab and the in-app header are the same drawing. The cover uses the hero's
Alesia figure from [`SiegeMotif.tsx`](../../web/src/components/hero/SiegeMotif.tsx):
the town, the two concentric walls Caesar built at Alesia, and arrowheads pressing
in from the outer perimeter and out from the town.

Colours are the `tailwind.config.ts` tokens (`agent` `#005BCC`, `ink` `#141A1F`,
`muted` `#5E676E`, `faint` `#939A9F`, `line` `#E6E9EC`) and the type is the same
Helvetica-first stack, with no webfont fetched.

Two deliberate departures from the running site:

- **The logo takes the app mark's 1.3/24 stroke, not the favicon's 2/24.** The
  heavier weight exists so the figure survives a 16px tab; at 512 it reads clumsy.
- **The cover's motif sits at 0.62 opacity, not the site's near-invisible wash.**
  On the site it is decoration behind body copy. A cover is judged as a thumbnail
  in a gallery, where that weight disappears altogether.

## The partner strip

`build-strip.py` flattens the landing page's `BuiltWith` marquee. It keeps the
order, the per-logo optical heights (the four viewBoxes carry different internal
padding, so one shared height leaves the row visibly uneven) and the colour each
brand pack ships. It drops only what a still image cannot carry: the scroll, the
three duplicate passes and the right-edge fade mask.

**Nothing is recoloured.** Every fill in the four vendored files is already
literal — `#F50DB4`, `#141A1F`, `#0C0A1D`, `#000000` — so they are inlined
untouched, and inlined rather than referenced so the render cannot depend on a
file load.

**There is no dark-ground cut, deliberately.** Three of the four marks are
single-ink because their owners publish them that way, so a dark version would
mean recolouring other companies' logos — and per
[`web/public/logos/README.md`](../../web/public/logos/README.md), an inaccurate
mark misrepresents a brand more visibly than no mark at all. Those marks are the
trademarks of their respective owners and appear as attribution; they do not
imply endorsement.
