# Brand assets — ETHGlobal submission

| File | Size | Where it goes |
|---|---|---|
| `scipio-logo-512.png` | 512×512 | Submission **Logo** field (square icon) |
| `scipio-cover-640x360.png` | 640×360 (16:9) | Submission **Cover image** field |

Both are generated from the HTML sources beside them, so they can be regenerated
rather than re-drawn:

```sh
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --screenshot=scipio-logo-512.png --window-size=512,512 file://"$PWD"/logo.html
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --screenshot=scipio-cover-640x360.png --window-size=640,360 file://"$PWD"/cover.html
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
