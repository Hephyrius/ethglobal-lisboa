"""Flatten the landing page's "Built with" marquee into a static banner.

The strip on the site is an animated marquee of four vendored SVGs. A banner
cannot move, so this keeps everything the motion was carrying — order, the
per-logo optical heights, the colours each brand pack ships — and drops only
the scroll, the duplicate passes and the right-edge fade mask.

Each mark is inlined rather than referenced, so the PNG cannot depend on a file
load, and nothing is recoloured: every fill in these four files is already
literal (`#F50DB4`, `#141A1F`, `#0C0A1D`, `#000000`), so they go in untouched.
"""

import pathlib
import re
import sys

REPO = pathlib.Path("/Users/charlottelynnemelkun/Desktop/web3-subgraph/ethglobal-lisboa")
LOGOS = REPO / "web" / "public" / "logos"
OUT = pathlib.Path(sys.argv[1])

# Order and relative heights are BuiltWith.tsx's PARTNERS array. The heights are
# the `sm:` cut doubled: the four viewBoxes carry different amounts of internal
# padding, so a single height leaves the row optically uneven, and those ratios
# are the correction someone already made by eye.
PARTNERS = [
    ("Uniswap", "uniswap.svg", 44),
    ("1inch", "1inch.svg", 36),
    ("The Graph", "thegraph.svg", 36),
    ("ETHGlobal", "ethglobal.svg", 50),
]


def load(name: str) -> str:
    svg = (LOGOS / name).read_text().strip()
    # Defensive: the vendored files already have their intrinsic width/height
    # dropped so CSS alone drives size, but re-dropping costs nothing and a
    # stray width= would silently override the height rule and skew the row.
    svg = re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
    assert svg.startswith("<svg"), f"{name} does not start with <svg>"
    assert "viewBox" in svg, f"{name} lost its viewBox"
    return svg


marks = []
for label, filename, height in PARTNERS:
    marks.append(
        f'      <li class="mark" style="--h:{height}px" aria-label="{label}">\n'
        f"        {load(filename)}\n"
        f"      </li>"
    )

html = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;width:1200px;height:200px;overflow:hidden}
  body{
    background:#FFFFFF;
    font-family:'Helvetica Neue',Helvetica,Inter,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
    display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:30px;
  }
  .label{
    font-size:12px; letter-spacing:.18em; text-transform:uppercase;
    color:#939A9F; font-weight:500;
  }
  .row{
    list-style:none; margin:0; padding:0;
    display:flex; align-items:center; gap:96px;
  }
  /* Height drives size; width follows the viewBox so nothing is distorted. */
  .mark{display:flex; align-items:center}
  .mark svg{height:var(--h); width:auto; display:block}
</style></head>
<body>
  <p class="label">Built with</p>
  <ul class="row">
__MARKS__
  </ul>
</body></html>
""".replace("__MARKS__", "\n".join(marks))

OUT.write_text(html)
print(f"wrote {OUT} ({len(html)} bytes, {len(PARTNERS)} marks inlined)")
