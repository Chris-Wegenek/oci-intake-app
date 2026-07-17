# OCI architecture diagram layout conventions

These conventions follow Oracle's official reference-architecture style (Oracle
Enterprise Landing Zone, CIS landing zone, hub-and-spoke DRG patterns) and the
established look of this team's existing BOM diagrams. Follow them so every
generated diagram reads like the rest of the portfolio.

## Nesting hierarchy (outermost to innermost)

1. **Tenancy** — thin grey dashed rectangle around everything OCI-owned.
   Label top-left ("<Customer> OCI Tenancy").
2. **Governance band** — inside the tenancy, above the regions: a
   `compartment`-styled strip listing landing-zone compartments, with a row of
   governance service icons (Federated IAM, Public DNS/GTM, Cloud Guard,
   Logging, Monitoring, Vault keys). Title it "Common governance and regional
   services".
3. **Region** — large rounded light-grey box per OCI region. Primary region on
   top, DR region below it. Label centered at top ("Primary OCI Region",
   "Secondary OCI Region for DR"), with a one-line scope subtitle.
4. **VCN** — red/orange dashed box. Label = VCN name, then CIDR and
   "DRG attachment" on the next line (e.g. "Hub VCN\n10.10.0.0/16 | DRG
   attachment"). Hub VCN sits left; spoke VCNs line up to its right, one per
   tier, in tier order; non-prod spoke last.
5. **Subnet** — finer dashed box inside a VCN. Label = subnet purpose + CIDR
   (e.g. "Tier 1 Private App Subnet\n10.20.1.0/24"). Public/DMZ subnets at the
   top of a VCN, private routing/inspection in the middle, shared services and
   data subnets below. App subnet above data subnet inside each spoke.

## Placement rules

- **External actors** (users, on-prem WAN, remote sites, other clouds, SaaS,
  SIEM) live OUTSIDE the tenancy: left edge for ingress/on-prem, right edge
  for cloud/SaaS destinations. Use `external` style.
- **Connectivity chain** on the left, ordered: on-prem/WAN box → CPE icon →
  FastConnect → Shared DRG (inside hub VCN region area). Internet Gateway at
  the hub's top-left, NAT + Service Gateway between hub and spokes.
- **The DRG is the visual center of gravity** — hub-spoke edges radiate from
  it. A second DRG anchors the DR region with a "Remote peering / DR routing"
  edge between the two.
- **Per-tier spokes are identical templates**: VM apps icon in app subnet,
  SQL Server/Oracle DB icon in data subnet, a backup bucket box beneath.
  Repetition is the point — readers compare tiers at a glance.
- **DR region mirrors the primary** with tier-aligned DR spoke VCNs
  (standby/pilot-light/restore VMs, replicated DB, DR target buckets) plus an
  orchestration VCN (Full Stack DR) on the left and a "DR readiness services"
  summary panel (`plain` style) on the right.
- **Notes band** at the very bottom of the page (`note` style): DR pattern
  explanations, assumptions, per-tier strategies. Bold lead-ins like
  "Tier 1 warm standby:" written inline.

## Edge conventions

- `solid` — live traffic / primary connectivity (HTTPS, BGP, routed
  inspection). Block arrowheads.
- `dashed` — logical/secondary links (secondary FastConnect, IPSec fallback,
  SaaS integration, private connectivity to other clouds).
- `backup` — fine-dotted grey with open arrowheads for backup/replication
  flows (DB → bucket, bucket → DR bucket replication). Route them vertically
  between regions.
- Label every edge that crosses a container boundary; keep labels under five
  words.

## Sizing and spacing

- Page ~2600×2050 for a two-region landing zone; grow width, not density.
- Icons 64–84 px; keep one icon size per diagram.
- Leave 24+ px padding inside every container; never let dashed borders touch.
- Container label rows need ~36 px clear space at the top of the box.

## Color palette (sampled from the reference Oracle BOM diagram)

- Burnt orange `#AE562C` for VCN/subnet borders and their bold titles;
  brighter `#BB501C` for compartment borders and note-box accents
- Dark slate-teal `#2D5967` is the icon color (comes from the stencils —
  never recolor library icons)
- Warm near-black `#312D2A` for body text; `#6B6560` for subtitles/CIDRs
- Warm greys: `#9E9892` tenancy/plain borders, `#C6C1BC` region borders,
  `#F5F4F2` region fill, `#55504B` edges, `#8B857F` backup flows
- Everything else stays white — the diagrams read as line drawings.
  These constants live in `scripts/build_diagram.py` (CONTAINER_STYLES,
  EDGE_STYLES) and `scripts/export_png.py` (CONTAINER, EDGE) — keep the two
  in sync if you adjust them.
