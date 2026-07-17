# OCI networking economics — the facts that drive these diagrams

The reason an OCI topology diagram lands: **most of the boxes are free.** AWS
meters the plumbing; OCI mostly doesn't. Annotate the diagram accordingly.

## What is $0 on OCI

| Component | OCI charge |
|---|---|
| DRG (Dynamic Routing Gateway) + VCN attachments | **$0** |
| DRG remote peering (inter-region backbone) | **$0** |
| VCN, subnets, route tables, security lists/NSGs | **$0** |
| Internet Gateway | **$0** |
| NAT Gateway (hours *and* per-GB) | **$0** |
| Service Gateway / private endpoints | **$0** |
| Site-to-Site VPN (IPSec), redundant tunnels | **$0** |
| Public IPv4 (ephemeral & reserved) | **$0** |
| IP address management | **$0** (built into the VCN) |
| Network Load Balancer | **$0** |
| DNS hosted zones | **$0** ($0.85 / 1M queries) |
| Inbound data transfer | **$0** |

## What actually costs money

| Component | Rate |
|---|---|
| FastConnect port | $1.275/port-hr (10 Gbps tier) ≈ **$931/mo** |
| Outbound data transfer | first **10 TB/mo free**, then ~$0.0085/GB (AWS: $0.09/GB) |
| Flexible Load Balancer | ~$0.0113/LB-hr |
| Compute (Ampere A1) | $0.01/OCPU-hr + $0.0015/GB-hr |

FastConnect does **not** meter data transfer — only the port.

## AWS → OCI networking map (from a real customer bill)

AWS networking total **$41,874/mo**; **$29,750/mo (71 %) maps to $0 on OCI.**

| AWS line item | $/mo | OCI equivalent | OCI |
|---|---:|---|---|
| Transit Gateway (attachment-hrs + data) | 22,901.93 | DRG + remote peering | **free** |
| Data Transfer (egress + inter-region) | 5,979.45 | Outbound data transfer | 10 TB free, then $0.0085/GB |
| Site-to-Site VPN (connection-hrs) | 4,103.40 | OCI Site-to-Site VPN | **free** |
| AWS Transfer Family (endpoint-hrs) | 2,464.37 | SFTPGo on Compute → Object Storage | ~$196/mo |
| Public IPv4 (in-use + idle) | 1,689.34 | OCI Public IP | **free** |
| Verified Access (app-hours) | 1,478.65 | WAF + Bastion/IAM | no per-app hourly |
| Elastic Load Balancing | 1,106.00 | Network LB / Flexible LB | NLB free |
| PrivateLink / VPC endpoints | 795.28 | Service Gateway | **free** |
| Direct Connect | 654.22 | FastConnect | port-hour only |
| Global Accelerator | 376.49 | LB + backbone | no accelerator fee |
| IPAM | 260.00 | VCN IP management | **free** |
| Route 53 | 64.84 | OCI DNS | zones free |

**Why the gap:** AWS charges per *construct-hour* — every TGW attachment, every
VPN connection, every endpoint, every idle IP has a meter. OCI charges for
capacity you consume (compute, dedicated ports, egress above the free tier) and
treats the network fabric as part of the platform.

## AWS Transfer Family replacement (the sub-project)

The bill's $2,464/mo was **99.99 % per-endpoint fee** ($0.30/endpoint-hr ×
8,928 endpoint-hours); actual data was 6.04 GB → $0.21. The 12 endpoints were
in **2 regions** across dev/prod/corp accounts, *not* 12 locations — check
before you architect 12 of anything.

**Option 1 — SFTPGo on OCI Compute** (recommended)
Ampere A1 VM per region, SFTPGo community edition, Object Storage as backend
via the S3-Compatibility API
(`https://{namespace}.compat.objectstorage.{region}.oraclecloud.com`), NLB in
front (free). *2 regions single-node: **$59/mo**; HA 2×2: **$117/mo**; all 12
endpoints isolated: **$209/mo**.* No license, no per-endpoint fee.

**Option 2 — Oracle SOA Suite / MFT on Marketplace**
2× WebLogic nodes + Flexible LB + Autonomous DB repo = $280/mo infra, plus
license-included **$0.7231/OCPU-hr** × 4 OCPU × 730 = **$2,111/mo** →
**$2,392/mo total ≈ break-even with AWS.** Worth it only if the customer needs
MFT's governance, B2B protocols, and orchestration.

⚠️ **$0.36155 is the per-vCPU comparison price, not BYOL.** 1 OCPU = 2 vCPU, so
it's the same rate expressed differently. BYOL is a separate, lower, unquoted
rate. Getting this wrong halves the license line and invalidates the
recommendation.

## OCI region mapping for customer site-areas

| Customer area | OCI region | id |
|---|---|---|
| US East | US East (Ashburn) | `us-ashburn-1` |
| US West | US West (Phoenix) | `us-phoenix-1` |
| Germany / Europe | Germany Central (Frankfurt) | `eu-frankfurt-1` |
| Hong Kong / Taiwan / China | Japan East (Tokyo) | `ap-tokyo-1` |
| Singapore / Malaysia | Singapore | `ap-singapore-1` |
| Korea | South Korea Central (Seoul) | `ap-seoul-1` |
| Japan | Japan East (Tokyo) | `ap-tokyo-1` |
| Australia | Australia East (Sydney) | `ap-sydney-1` |

**There is no OCI Hong Kong region.** Taiwan/China/HK traffic goes to Tokyo (or
Singapore). Tokyo therefore serves two site-areas → merge them into one region
card. Verify any region against the current OCI region list before drawing it.
