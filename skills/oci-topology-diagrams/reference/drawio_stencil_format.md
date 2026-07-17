# draw.io stencil format — how to get real Oracle icons out of a shape library

A `.xml` draw.io shape library (e.g. `OCI Library.xml`) is **not** readable XML
of shapes. It is a nested encoding. Decode it in this exact order:

```
<mxlibrary>[ {"xml": "<base64>", "w":…, "h":…, "title":"DRG"}, … ]</mxlibrary>
        │
        ├─ 1. parse the mxlibrary body as JSON  → list of entries
        ├─ 2. base64-decode entry["xml"]
        ├─ 3. raw-deflate decompress            zlib.decompress(data, -15)   ← wbits = -15, NOT 15
        ├─ 4. urllib.parse.unquote(...)         the deflated payload is URL-encoded
        └─ 5. you now have mxGraphModel XML     → read each mxCell's `style`
```

The style string of a shape cell carries the drawing itself:

```
shape=stencil(<base64-of-another-deflated-stencil-xml>);fillColor=#C74634;…
```

So step 5 recurses: base64 → raw deflate → the `<shape>` element, whose
`<foreground>` contains the actual geometry.

## The stencil geometry language

Coordinates live in the stencil's own `w`/`h` space (usually 0–100) and get
scaled to the cell geometry. Only a handful of commands matter:

| element | meaning |
|---|---|
| `<path>` | begins a subpath |
| `<move x y>` | moveTo |
| `<line x y>` | lineTo |
| `<curve x1 y1 x2 y2 x3 y3>` | cubic bezier |
| `<close>` | closePath |
| `<fillstroke>` / `<fill>` | flush the current subpath with the current fill colour |
| `<ellipse>`, `<rect>`, `<roundrect>` | primitives — expand to path ops if you care |

Everything else (`<strokewidth>`, `<dashpattern>`, `<fontsize>`) can be ignored
for icon extraction.

## Gotchas that cost time

- **`wbits=-15`.** Using the default `zlib.decompress` fails with "incorrect
  header check". The payload is *raw* deflate, no zlib header.
- **`fillColor=none`.** Some paths are stroke-only or invisible. If you feed
  `"none"` to a hex parser you get `ValueError: invalid literal for int()`.
  Skip any colour that doesn't start with `#`.
- **Colour is per-cell, not per-path.** A stencil is monochrome geometry; the
  colour comes from the containing cell's `style`. Carry it down.
- **Multiple `<path>` blocks per stencil.** Keep them as separate filled paths,
  in order — z-order matters (a white inner path is often drawn over a red
  outer one).

## Normalized output (`icons_data.json`)

Flatten to something renderer-agnostic:

```json
{
  "DRG": {
    "w": 100.0, "h": 100.0,
    "paths": [
      { "color": "#C74634",
        "ops": [["M", 12.0, 4.0], ["L", 88.0, 4.0],
                ["C", 92.0, 4.0, 96.0, 8.0, 96.0, 12.0], ["Z"]] }
    ]
  }
}
```

`ops` are trivially replayable in **pycairo** (`move_to` / `line_to` /
`curve_to` / `close_path`), in an **SVG `d=` attribute**, and in **draw.io** as
an inline `data:image/svg+xml,<urlencoded svg>` image — one decode, three
render targets.

## Re-embedding icons into a `.drawio`

Don't try to re-emit stencil style strings. Emit an SVG data URI instead:

```python
style = ('shape=image;verticalLabelPosition=bottom;verticalAlign=top;'
         f'imageAspect=1;aspect=fixed;image=data:image/svg+xml,{quote(svg, safe="/")};')
```

`safe="/"` matters — draw.io tolerates `/` unescaped and it keeps the file
smaller. The result opens in diagrams.net with crisp, editable, correctly
coloured Oracle icons.
