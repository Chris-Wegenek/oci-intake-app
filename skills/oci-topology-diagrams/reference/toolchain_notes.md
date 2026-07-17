# Toolchain notes — the environment traps

Save yourself the hour these cost.

## Python

- **pycairo is the whole renderer.** `pip install pycairo`. No `cairosvg`, no
  `matplotlib`, no headless browser. `ImageSurface` → PNG (render at `scale=2`
  and `ctx.scale(2,2)` for crisp text), `SVGSurface` → SVG. Same context code
  drives both.
- Font: `ctx.select_font_face("DejaVu Sans", …)` — present everywhere, and its
  metrics are what the layout constants were tuned against.
- `zlib.decompress(data, -15)` for draw.io payloads (raw deflate). Default
  wbits fails.
- Colour parsing: guard `if not col.startswith("#"): continue` — stencils carry
  `fillColor=none`.

## Node (for the docx/pptx deliverables built alongside the diagrams)

- **The npm registry may be blocked (403).** Don't `npm install`. The needed
  packages are usually already vendored:

  ```bash
  export NODE_PATH=/usr/local/lib/node_modules_global/lib/node_modules
  node generate_deck.js
  ```

  `docx`, `pptxgenjs`, and `sharp` were all available there.
- `docx` gotcha: a `Paragraph` with multiple children closes `]}));` — the `}`
  closes the options object. Writing `]));` is a silent `SyntaxError` far from
  the actual line.

## Filesystem

- `rm` can fail with "Operation not permitted" on previously-written output
  files. Render into a fresh timestamped directory instead of fighting it.

## Embedding diagrams in slides

Render a slide-specific variant (`--limit 2 --no-legend`) rather than shrinking
the poster. Target ≥ 7.5" wide on a 13.3" widescreen slide; the aspect ratio of
a legend-free 2-region diagram (~1.8:1) fits that well.

Then **render the deck back to images and look at every slide.** Text that is
fine at 100 % is unreadable at slide scale, and this is the only way to catch
it.
