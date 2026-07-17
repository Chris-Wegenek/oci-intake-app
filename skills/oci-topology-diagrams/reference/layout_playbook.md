# Layout playbook — what makes these topologies readable

Hard-won rules from building the global customer-sites → OCI diagram. Ignore
them and the diagram *renders* but doesn't *read*.

## Structure

```
┌──────────── W = 1840 ────────────────────────────────────────────────┐
│  header (86px): title 24pt bold + subtitle 12.5pt grey               │
├───────────────────┬──────────┬──────────────────────────────┬────────┤
│ customer sites    │ corridor │  cloud region card           │ spine  │
│ band (760px)      │ (150px)  │  VCN › subnets › services    │ (34px) │
│   hub site (big)  │          │  DRG (one, centred)          │        │
│   spoke, spoke…   │          │                              │        │
├───────────────────┴──────────┴──────────────────────────────┴────────┤
│  legend (120px)                                                       │
│  cost panel (150px)                                                   │
└───────────────────────────────────────────────────────────────────────┘
```

- **Left = what the customer owns. Right = what they'd buy.** Never mix.
- **The 150 px corridor is non-negotiable.** It is the only place the
  hub→DRG link and its price label live. Squeeze it and labels collide with
  the cards.
- **The backbone spine** (a 4 px vertical bar on the far right) is what turns
  N disconnected pictures into one *global* network. Dashed leaders from every
  DRG to the spine; the label runs vertically along it.

## Hub-and-spoke, drawn honestly

Only the **hub** site crosses the corridor. Spokes connect to the hub, not to
the cloud. This is both accurate (that's how the customer's WAN actually works)
and the thing that keeps edge count linear instead of quadratic.

Emphasize the hub: bigger box, 2.0 lw Oracle-red border, a `◢ Regional VPN hub
/ edge` tag. Spokes are small grey cards.

## Merging regions

Group site-areas by region id (`rid`). Two areas landing in `ap-tokyo-1` must
share **one region card, one DRG, one VCN**, with the card spanning both site
bands vertically:

```python
groups = {}
for R in REGIONS:
    groups.setdefault(R["rid"], []).append(R)

group_h = sum(member_heights) + band_gap * (len(members) - 1)
# one card at (reg_x, group_top, reg_w, group_h); DRG at ry + rh/2
# then each member draws its own left band and connects to the SHARED drg_in
```

Drawing two Tokyo cards is a factual error — the customer only pays for one.

## Line semantics (be consistent, and put it in the legend)

| link | colour | style | weight |
|---|---|---|---|
| FastConnect | teal `#2D5967` | solid | 3.0 |
| Site-to-Site VPN | Oracle red `#C74634` | dashed | 2.0 (+ a 1.4 second tunnel — IPSec is redundant by default) |
| spoke → hub | slate `#6E8895` | solid | 1.2 |
| backbone / DRG peering | teal | dashed | 1.3, no arrowhead |

Dashed = logical/overlay. Solid = dedicated circuit. Weight = importance.

## Text legibility

- **Knock-out box behind every edge label.** Fill white under the text extents
  before drawing it, or the label disappears into whatever it crosses.
- Sizes: 24 title / 13.5 card title / 11.5 hub name / 10.2 spoke / 9.2 sub /
  8.x captions. Below ~8 pt nothing survives a projector.
- Anchors matter: `w` / `c` / `e`. Centre icon captions under the icon (`c`).

## Slides vs. documents

The same spec must produce two different images:

- **Document / poster:** full region list, legend + cost panel on.
- **Slide:** `--limit 2 --no-legend`. Two regions is enough to make the pattern
  obvious, and the legend eats the vertical space the image needs to scale up.
  A full-height 8-region diagram shrunk onto a 13.3×7.5" slide is unreadable —
  this was caught only by rendering the deck to images and looking at them.

## Cost annotation

Put the price **on the link** (`Site-to-Site VPN · $0/mo`), not only in a
table. `$0` on a line is the single most persuasive element in the diagram.
Green for free, red for a real charge, and a totals panel underneath.

## Verification loop

Render → convert to PNG → **crop and zoom the busy areas** (corridor, merged
region, legend) → look. Every layout bug found in this project — overlapping
subnet boxes, the DRG label sitting on the VCN border, illegible slide
diagrams — was found by looking at a crop, never by reading the code.
