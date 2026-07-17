---
name: oci-topology-diagrams
description: Build customer-facing OCI network topology diagrams (customer sites → DRG/VCN/VPN/FastConnect) that render as PNG, SVG, and editable draw.io from one JSON spec, using authentic Oracle stencil icons. Use when asked to diagram a network architecture, map on-prem sites to OCI regions, show DRGs/VCNs/VPN tunnels, convert an AWS network layout to OCI, or produce a .drawio the customer can edit.
---

# OCI Topology Diagrams

A proven pipeline for turning a customer's site list into a presentation-grade
network topology, with real Oracle icons and OCI-accurate cost annotations.

## The core idea: one display list, three outputs

Do **not** hand-write draw.io XML and separately hand-draw a picture. Build an
intermediate list of primitives (`rect`, `icon`, `text`, `edge`) with absolute
coordinates once, then walk it twice:

- pycairo → high-res PNG + vector SVG (for decks and docs)
- mxGraph XML → `.drawio` (customer can open and edit it)

Both outputs are pixel-identical because they share the coordinates. This is
what `scripts/topology.py` does; everything else is data.

## Quick start

```bash
pip install pycairo                       # only hard dependency
python3 scripts/topology.py assets/example_topology.json --out ./build
# → build/oci_network_diagram.png / .svg / .drawio
```

Useful flags: `--limit 2` (render only the first N regions — good for a slide
example), `--no-legend` (drop the legend + cost panel so the diagram scales up
legibly on a slide), `--name mydiagram`, `--icons path/to/icons_data.json`.

## Writing a spec

`assets/example_topology.json` is the reference. One entry per **site-area**:

```json
{
  "area": "US East",                          // left-hand band title
  "oci":  "US East (Ashburn)",                // right-hand region card title
  "rid":  "us-ashburn-1",                     // region id — ALSO the merge key
  "vcn":  "10.10.0.0/16",
  "hub":  { "name": "Chelmsford Campus",
            "sub":  "Bldg 15 & 12 · W-Hemisphere VPN access",
            "conn": "FastConnect 5 Gbps" },   // starts with "FastConnect" ⇒ solid teal + $ label
  "spokes": [["Chelmsford Mfg", "Manufacturing"]],
  "anchor": "FSX · AppStream · Verified Access",
  "sftpgo": true                              // optional SFTPGo + Object Storage inset
}
```

Two site-areas with the **same `rid`** are automatically merged into a single
region card sharing one DRG and one VCN — the correct picture when, e.g., both
Taiwan/China and Japan traffic lands in `ap-tokyo-1`. Don't duplicate region
cards by hand.

## Before you draw: check the facts

1. **Region must exist.** There is no OCI Hong Kong region. Map to the nearest
   real one (`reference/oci_regions.md`).
2. **Check the data store first** rather than assuming — customer site data,
   OCI price lists, and shape maps usually already exist as JSON in the project.
3. **Costs come from the price data, not from memory.** DRG, VCN, subnets,
   route tables, S2S VPN, Internet/NAT/Service gateways are **$0 on OCI**. The
   only recurring networking charges are FastConnect ports and egress beyond
   10 TB/mo. See `reference/oci_networking_costs.md`.

## Icons

`assets/icons_data.json` holds 32 official Oracle shapes already decoded into
plain path ops (`M/L/C/Z` + fill colour): DRG, VCN, CPE, VM, Buckets,
ObjectStorage, LoadBalancer, Database, Bastion, InternetGateway, NATGateway,
ServiceGateway, FileStorage, Vault, Logging, Monitoring, Compartment, and more.

To decode a *different* draw.io stencil library, run
`scripts/extract_icons.py` — it reverse-engineers the `.xml` library format
(base64 → raw deflate → URL-decode → mxGraphModel → stencil paths). Format
notes: `reference/drawio_stencil_format.md`.

## Layout rules that made it work

Detailed in `reference/layout_playbook.md`. The short version: sites on the
left, cloud regions on the right, a 150 px connection corridor between them,
a vertical backbone spine on the far right joining every DRG; hub site drawn
larger and outlined in Oracle red; spokes feed the hub, only the hub crosses
the corridor; every edge label gets a white knock-out box so it stays readable
where it crosses a line.

## Verify before you ship

Render, then actually **look** at the PNG (crop and zoom regions). Text
collisions, edges vanishing behind cards, and illegible labels at slide scale
are the failure modes — they are invisible unless you inspect the output.
