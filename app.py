#!/usr/bin/env python3
import warnings

warnings.filterwarnings("ignore", message="'cgi' is deprecated.*", category=DeprecationWarning)

import cgi
import json
import math
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
from pypdf import PdfReader

import bom_export


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
UPLOAD_DIR = Path(
    os.environ.get(
        "UPLOAD_DIR",
        "/tmp/oci-intake-uploads" if os.environ.get("VERCEL") else str(ROOT / "uploads"),
    ),
)
UPLOAD_DIR.mkdir(exist_ok=True)

PORT = int(os.environ.get("PORT", "8787"))
HOURS_PER_MONTH = 730

DEFAULT_SHAPE_KEY = "e6-standard-ax"
INTAKE_MODE_ON_PREM = "on_prem"
INTAKE_MODE_CLOUD_BILL = "cloud_bill"
PROVIDER_AUTO = "auto"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
OPENAI_DISABLED_MESSAGE = "OpenAI API calls are temporarily disabled."


def openai_api_enabled():
    flag = clean_text(os.environ.get("OPENAI_API_ENABLED")).lower()
    if flag:
        return flag in {"1", "true", "yes", "on"}
    return True


def openai_api_configured():
    return bool(clean_text(os.environ.get("OPENAI_API_KEY")))


LLM_WORKFLOW_CONTRACT = [
    "Upload step: inspect the spreadsheet, PDF, or bill export and identify each workload's core count, RAM, storage, application/workload name, and environment when present.",
    "CPU/core values from uploaded inventory are source vCPU/core counts; normalize them to OCI OCPUs for review using 2 vCPUs = 1 OCPU.",
    "Review step: the editable review table is the source of truth. User edits override values inferred during upload.",
    "Pricing step: price only the approved rows and edited values from the review table against the supplied OCI rate card and curated price catalog.",
    "Never invent OCI rates or use source-cloud spend as an OCI rate. Use the provided rate card/catalog for final pricing math and flag uncertain mappings for review.",
]


CANONICAL_INVENTORY_FIELDS = [
    {
        "key": "application_name",
        "label": "Application Name",
        "description": "Application, workload, server, VM, host, or inventory item name.",
        "aliases": [
            "application name",
            "application",
            "app name",
            "name",
            "product",
            "workload",
            "server name",
            "hostname",
            "host name",
            "vm name",
            "asset name",
            "resource id",
            "resourceid",
            "instance id",
            "tags.name",
            "tags.appid",
        ],
    },
    {
        "key": "environment",
        "label": "Environment",
        "description": "Environment such as prod, dev, qa, test, uat, disaster recovery, or staging.",
        "aliases": ["environment", "env", "tier", "stage", "lifecycle"],
    },
    {
        "key": "application_details",
        "label": "Application Details",
        "description": "Application description, type, function, business role, or notes.",
        "aliases": [
            "application details",
            "application type",
            "description",
            "business function",
            "app details",
            "role",
            "purpose",
            "resource id",
            "resourceid",
            "private ip",
            "configuration privateipaddress",
        ],
    },
    {
        "key": "application_details_application_version",
        "label": "Application Details: Application Version",
        "description": "Application, product, or platform version.",
        "aliases": ["application version", "app version", "version", "release"],
    },
    {
        "key": "application_details_operating_system",
        "label": "Application Details: Operating System",
        "description": "Operating system name and version.",
        "aliases": ["operating system", "os", "os version", "platform", "tags.os"],
    },
    {
        "key": "application_details_number_of_servers",
        "label": "Application Details: Number of Servers",
        "description": "How many application servers, VMs, hosts, nodes, or instances this row represents.",
        "aliases": ["number of servers", "server count", "servers", "instances", "nodes", "vm count", "quantity", "qty"],
    },
    {
        "key": "application_details_number_of_cpu_cores_per_server",
        "label": "Application Details: OCPUs",
        "description": "OCPU count per server. Uploaded spreadsheet CPU values are assumed to be vCPUs and converted using 2 vCPUs = 1 OCPU.",
        "aliases": [
            "number of cpu cores per server",
            "number of cpus",
            "cpu/vcpu",
            "cpu vcpu",
            "cpu",
            "cpus",
            "cpu count",
            "v cpu",
            "vcpu",
            "vcpus",
            "vcpu count",
            "virtual cpu",
            "virtual cpus",
            "cores",
            "core count",
            "cpu cores",
            "processor cores",
            "processors",
            "num cpu",
            "num cpus",
            "cpu cores per vm",
            "vcpus per vm",
        ],
    },
    {
        "key": "application_details_memory_per_server_gb",
        "label": "Application Details: Memory per server (GB)",
        "description": "RAM or memory per server in GB.",
        "aliases": [
            "memory per server",
            "memory per server gb",
            "memory per vm",
            "memory in gb",
            "memory",
            "memory gb",
            "memory (gb)",
            "ram",
            "ram gb",
            "ram (gb)",
            "gb ram",
            "mem",
            "mem gb",
            "memory size",
            "ram size",
        ],
    },
    {
        "key": "application_details_chipset",
        "label": "Application Details: Chipset",
        "description": "CPU chipset, processor family, architecture, or platform family.",
        "aliases": ["chipset", "processor family", "cpu type", "architecture", "processor", "hardware family"],
    },
    {
        "key": "application_details_local_storage_gb",
        "label": "Application Details: Local Storage (GB)",
        "description": "Local VM disk, OS disk, data disk, or directly attached block storage in GB.",
        "aliases": [
            "local storage",
            "storage",
            "storage gb",
            "total storage",
            "total storage gb",
            "allocated storage",
            "allocated storage gb",
            "disk gb",
            "disk size",
            "disk capacity",
            "data disk",
            "os disk",
            "block storage",
        ],
    },
    {
        "key": "application_details_shared_storage_gb",
        "label": "Application Details: Shared Storage (GB)",
        "description": "Shared, NAS, NFS, SMB, ETL, or file storage in GB.",
        "aliases": ["shared storage", "nas", "nfs", "file storage", "shared disk", "smb"],
    },
    {
        "key": "database_details_number_of_database_servers",
        "label": "Database Details: Number of Database Servers",
        "description": "How many database servers, database nodes, or DB instances this row represents.",
        "aliases": ["number of database servers", "database servers", "db servers", "db nodes", "database instances"],
    },
    {
        "key": "database_details_number_of_cpu_cores_per_server",
        "label": "Database Details: OCPUs",
        "description": "Database OCPU count per server. Uploaded spreadsheet CPU values are assumed to be vCPUs and converted using 2 vCPUs = 1 OCPU.",
        "aliases": [
            "database cpu",
            "db cpu",
            "database cpus",
            "db cpus",
            "number of cpu cores per server",
            "number of cpus",
            "database cores",
            "db cores",
            "database vcpu",
            "database vcpus",
            "db vcpu",
            "db vcpus",
            "database cpu count",
            "db cpu count",
            "cpu cores per server",
        ],
    },
    {
        "key": "database_details_memory_per_server_gb",
        "label": "Database Details: Memory per server (GB)",
        "description": "Database RAM or memory per DB server in GB.",
        "aliases": [
            "database memory",
            "db memory",
            "database memory gb",
            "db memory gb",
            "database ram",
            "db ram",
            "database ram gb",
            "db ram gb",
        ],
    },
    {
        "key": "database_details_total_allocated_storage_gb",
        "label": "Database Details: Total Allocated Storage (GB)",
        "description": "Database storage, allocated DB storage, datafile size, or total database disk in GB.",
        "aliases": [
            "database total allocated storage",
            "db total allocated storage",
            "database storage",
            "db storage",
            "database size",
            "db size",
            "database total storage",
            "db total storage",
        ],
    },
]

FULL_SERVICE_BETA_FIELDS = [
    {
        "key": "source_provider",
        "label": "Source Provider",
        "description": "Source platform such as AWS, Azure, GCP, OCI, VMware, on-prem, or a billing/export vendor.",
        "aliases": ["provider", "source provider", "cloud provider", "vendor", "publisher", "billing provider", "cloud"],
    },
    {
        "key": "source_service",
        "label": "Source Service",
        "description": "Source service family or meter category such as EC2, S3, EBS, Azure VM, Blob Storage, GCP Compute, or NAS.",
        "aliases": [
            "service",
            "service name",
            "service family",
            "meter category",
            "product code",
            "lineitem productcode",
            "product/service",
            "resource type",
        ],
    },
    {
        "key": "source_product",
        "label": "Source Product",
        "description": "Detailed product, SKU, meter, operation, usage type, or item description from a cloud bill or CMDB.",
        "aliases": [
            "product",
            "product name",
            "sku",
            "sku name",
            "meter name",
            "meter sub category",
            "meter subcategory",
            "usage type",
            "operation",
            "item description",
            "line item description",
            "resource description",
        ],
    },
    {
        "key": "source_region",
        "label": "Source Region",
        "description": "Source cloud region, datacenter, location, or availability zone.",
        "aliases": ["region", "location", "availability zone", "az", "datacenter", "data center", "resource location"],
    },
    {
        "key": "usage_quantity",
        "label": "Usage Quantity",
        "description": "Consumed usage amount from a bill or inventory export.",
        "aliases": ["usage quantity", "usage amount", "consumed quantity", "quantity", "usagequantity", "usage amount", "usage"],
    },
    {
        "key": "usage_unit",
        "label": "Usage Unit",
        "description": "Unit for the consumed usage amount, such as GB-month, TB-month, request, hour, vCPU-hour, or instance-month.",
        "aliases": ["usage unit", "unit", "unit of measure", "pricing unit", "meter unit", "uom", "usageunit"],
    },
    {
        "key": "source_monthly_cost",
        "label": "Source Monthly Cost",
        "description": "Monthly source-cloud or on-prem cost when present; used for review, not as an OCI rate.",
        "aliases": ["cost", "monthly cost", "pretax cost", "pre tax cost", "unblended cost", "amortized cost", "charge", "amount"],
    },
    {
        "key": "oci_service_category",
        "label": "OCI Service Category",
        "description": "Editable target OCI service category inferred from the source row.",
        "aliases": ["oci service", "oci service category", "target service", "oracle service", "oracle cloud service"],
    },
    {
        "key": "oci_product",
        "label": "OCI Product",
        "description": "Editable target OCI product or price-list item inferred from the source row.",
        "aliases": ["oci product", "target product", "oracle product", "mapped product", "mapped sku", "target sku"],
    },
    {
        "key": "mapping_confidence",
        "label": "Mapping Confidence",
        "description": "Confidence score or review status for the full-service beta mapping.",
        "aliases": ["mapping confidence", "confidence", "match confidence", "mapping status", "review status"],
    },
]

CLOUD_BILL_FIELDS = [
    {
        "key": "source_provider",
        "label": "Provider",
        "description": "Detected source provider: AWS, Azure, or GCP.",
        "aliases": ["provider", "cloud provider", "vendor", "publisher"],
    },
    {
        "key": "source_account",
        "label": "Account / project",
        "description": "AWS account, Azure subscription, GCP project, or billing account.",
        "aliases": [
            "account",
            "account id",
            "usage account id",
            "subscription id",
            "subscription name",
            "project id",
            "project name",
            "billing account id",
        ],
    },
    {
        "key": "source_service",
        "label": "Source service",
        "description": "Cloud service family such as EC2, S3, Azure VMs, Blob Storage, GCP Compute, or Cloud Storage.",
        "aliases": [
            "service",
            "service name",
            "service description",
            "meter category",
            "product code",
            "product name",
            "consumed service",
        ],
    },
    {
        "key": "source_product",
        "label": "SKU / meter",
        "description": "Detailed SKU, meter, usage type, operation, or line item description.",
        "aliases": [
            "sku",
            "sku description",
            "meter name",
            "meter subcategory",
            "meter sub category",
            "usage type",
            "operation",
            "line item description",
            "resource description",
        ],
    },
    {
        "key": "source_region",
        "label": "Region",
        "description": "Cloud region, resource location, or availability zone.",
        "aliases": ["region", "location", "resource location", "availability zone", "zone"],
    },
    {
        "key": "usage_quantity",
        "label": "Usage quantity",
        "description": "Consumed usage amount from the source bill.",
        "aliases": ["usage amount", "usage quantity", "quantity", "qty", "consumed quantity", "usage.amount"],
    },
    {
        "key": "usage_unit",
        "label": "Usage unit",
        "description": "Unit of measure such as GB-month, vCPU-hour, request, hour, or quantity unit.",
        "aliases": ["usage unit", "unit", "unit of measure", "pricing unit", "usage.unit"],
    },
    {
        "key": "resource_ocpus",
        "label": "OCPUs",
        "description": "Normalized OCPU quantity inferred from explicit OCPU/vCPU bill lines or recognizable VM instance types.",
        "aliases": [
            "ocpu",
            "ocpus",
            "ocpu count",
            "ocpu quantity",
            "vcpu",
            "vcpus",
            "vcpu count",
            "cpu",
            "cpus",
            "cpu count",
            "core",
            "cores",
            "core count",
        ],
    },
    {
        "key": "resource_memory_gb",
        "label": "RAM (GB)",
        "description": "Normalized memory/RAM quantity in GB inferred from explicit memory bill lines or recognizable VM instance types.",
        "aliases": [
            "ram",
            "ram gb",
            "ram (gb)",
            "memory",
            "memory gb",
            "memory (gb)",
            "memory quantity",
            "gb ram",
            "mem gb",
        ],
    },
    {
        "key": "source_monthly_cost",
        "label": "Source cost",
        "description": "Source-cloud cost for review context only; OCI estimate uses OCI rates.",
        "aliases": ["cost", "source cost", "unblended cost", "net unblended cost", "pretax cost", "cost in billing currency"],
    },
    {
        "key": "source_currency",
        "label": "Currency",
        "description": "Source bill currency.",
        "aliases": ["currency", "billing currency", "billing currency code", "pricing currency"],
    },
    {
        "key": "source_period",
        "label": "Billing period",
        "description": "Usage or billing month/date from the source bill.",
        "aliases": ["billing period", "usage start date", "usage date", "date", "month"],
    },
    {
        "key": "source_tags",
        "label": "Tags / labels",
        "description": "Source tags, labels, dimensions, or resource metadata that identify workload ownership.",
        "aliases": ["tags", "labels", "resource tags", "system tags", "additional info"],
    },
    {
        "key": "oci_service_category",
        "label": "OCI service",
        "description": "Editable target OCI service category inferred from the source bill row.",
        "aliases": ["oci service", "target service", "oracle service", "service category"],
    },
    {
        "key": "oci_product",
        "label": "OCI product / SKU",
        "description": "Editable target OCI product or price-list item inferred from the source bill row.",
        "aliases": ["oci product", "target product", "oracle product", "mapped product", "mapped sku", "target sku"],
    },
    {
        "key": "mapping_confidence",
        "label": "Mapping confidence",
        "description": "Confidence score or review status for the OCI mapping.",
        "aliases": ["mapping confidence", "confidence", "match confidence", "review status"],
    },
]


def normalize_intake_mode(value):
    text = normalize(value)
    if text in {"cloud bill", "cloud billing", "cloud", "bill", "aws", "azure", "gcp"}:
        return INTAKE_MODE_CLOUD_BILL
    return INTAKE_MODE_ON_PREM


def normalize_provider_hint(value):
    text = normalize(value)
    if text in {"aws", "amazon", "amazon web services"}:
        return "aws"
    if text in {"azure", "microsoft", "microsoft azure"}:
        return "azure"
    if text in {"gcp", "google", "google cloud", "google cloud platform"}:
        return "gcp"
    return PROVIDER_AUTO


def inventory_fields(full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM):
    if intake_mode == INTAKE_MODE_CLOUD_BILL:
        return CLOUD_BILL_FIELDS
    if full_service_beta:
        return [*CANONICAL_INVENTORY_FIELDS, *FULL_SERVICE_BETA_FIELDS]
    return CANONICAL_INVENTORY_FIELDS


CANONICAL_FIELD_BY_KEY = {
    field["key"]: field
    for field in [*CANONICAL_INVENTORY_FIELDS, *FULL_SERVICE_BETA_FIELDS, *CLOUD_BILL_FIELDS]
}
NUMERIC_FIELD_KEYS = {
    "application_details_number_of_servers",
    "application_details_number_of_cpu_cores_per_server",
    "application_details_memory_per_server_gb",
    "application_details_local_storage_gb",
    "application_details_shared_storage_gb",
    "database_details_number_of_database_servers",
    "database_details_number_of_cpu_cores_per_server",
    "database_details_memory_per_server_gb",
    "database_details_total_allocated_storage_gb",
    "resource_ocpus",
    "resource_memory_gb",
}
CPU_FIELD_KEYS = {
    "application_details_number_of_cpu_cores_per_server",
    "database_details_number_of_cpu_cores_per_server",
    "resource_ocpus",
}
SIZE_FIELD_KEYS = {
    "application_details_memory_per_server_gb",
    "application_details_local_storage_gb",
    "application_details_shared_storage_gb",
    "database_details_memory_per_server_gb",
    "database_details_total_allocated_storage_gb",
    "resource_memory_gb",
}
FULL_SERVICE_FIELD_KEYS = {field["key"] for field in FULL_SERVICE_BETA_FIELDS}
CLOUD_BILL_FIELD_KEYS = {field["key"] for field in CLOUD_BILL_FIELDS}
SOURCE_SERVICE_FIELD_KEYS = FULL_SERVICE_FIELD_KEYS | CLOUD_BILL_FIELD_KEYS

SHAPE_DEFINITIONS = [
    {
        "key": "e4-standard",
        "label": "E4 Standard",
        "shortLabel": "E4",
        "family": "AMD flexible shape",
        "processorVendor": "amd",
        "computeSku": "B97384",
        "memorySku": "B97385",
        "computeRate": 0.0250,
        "memoryRate": 0.0015,
        "summary": "Lower memory rate with a mid-tier OCPU rate for steady general workloads.",
        "accent": "#2f5d28",
    },
    {
        "key": "e5-standard",
        "label": "E5 Standard",
        "shortLabel": "E5",
        "family": "AMD flexible shape",
        "processorVendor": "amd",
        "computeSku": "B97384",
        "memorySku": "B97385",
        "computeRate": 0.0300,
        "memoryRate": 0.0020,
        "summary": "Current generation AMD shape with identical E6 Standard compute and memory rates.",
        "accent": "#365f1c",
    },
    {
        "key": DEFAULT_SHAPE_KEY,
        "label": "E6 Standard Ax",
        "shortLabel": "E6 Ax",
        "family": "AMD Ax flexible shape",
        "processorVendor": "amd",
        "computeSku": "B112530",
        "memorySku": "B112531",
        "computeRate": 0.0138,
        "memoryRate": 0.0108,
        "summary": "Lower OCPU rate and higher memory rate; useful when compute-heavy rows dominate.",
        "accent": "#164f68",
    },
    {
        "key": "x9-standard",
        "label": "X9 Standard",
        "shortLabel": "X9",
        "family": "Virtual Machine Standard",
        "processorVendor": "intel",
        "computeSku": "X9-OCPU",
        "memorySku": "X9-MEMORY",
        "computeRate": 0.0400,
        "memoryRate": 0.0015,
        "summary": "Standard X9 VM shape using the public OCPU and memory rates from the supplied rate card.",
        "accent": "#7a3126",
    },
    {
        "key": "x12-standard-ax",
        "label": "X12 Standard Ax",
        "shortLabel": "X12 Ax",
        "family": "Intel Ax flexible shape",
        "processorVendor": "intel",
        "computeSku": "X12AX-OCPU",
        "memorySku": "X12AX-MEMORY",
        "computeRate": 0.0119,
        "memoryRate": 0.0114,
        "summary": "Standard X12 Ax shape using the public OCPU and memory rates from the supplied rate card.",
        "accent": "#8a6f24",
    },
]

SHAPE_LOOKUP = {shape["key"]: shape for shape in SHAPE_DEFINITIONS}

STORAGE_RATE_ITEMS = [
    {
        "sku": "B91961",
        "description": "Block Volume Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.0255,
        "notes": "VM OS / data disks",
    },
    {
        "sku": "B91962",
        "description": "Block Volume Performance Units (per GB-mo)",
        "unit": "Performance Units/GB-month",
        "rate": 0.0017,
        "notes": "Balanced performance: 10 performance units per block-volume GB",
    },
    {
        "sku": "B89057",
        "description": "File Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.3000,
        "notes": "NAS / ETL shared file storage",
    },
]

# Block-volume performance units billed per GB of block storage (BOM script uses Balanced = 10).
BLOCK_PERFORMANCE_UNITS_PER_GB = 10

# Windows OS licensing (BOM script): charged per OCPU-hour for rows detected as Windows.
WINDOWS_LICENSE_SKU = "B88318"
WINDOWS_LICENSE_RATE = 0.0920

# "Rightsize and Cut Costs": follows the Acceleron optimizer methodology — map to the OCI
# target memory ratio of 8 GB per OCPU instead of carrying over the source's (often
# over-provisioned) memory. Memory is capped at ocpus x 8 GB; OCPUs are unchanged.
RIGHTSIZE_MEM_PER_OCPU = 8.0
WINDOWS_LICENSE_ITEM = {
    "sku": WINDOWS_LICENSE_SKU,
    "description": "Compute - Windows OS (OCPU Per Hour)",
    "unit": "OCPU-hour",
    "rate": WINDOWS_LICENSE_RATE,
    "notes": "Windows OS licensing for OS-detected Windows rows, OCPU-hours x 730",
}

FULL_SERVICE_RATE_ITEMS = [
    {
        "key": "object_storage_standard",
        "sku": "B91628",
        "description": "Object Storage - Standard storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.0255,
        "category": "Storage",
        "notes": "Maps AWS S3 Standard, Azure Blob hot/standard, GCP Cloud Storage standard, and generic object stores.",
        "keywords": ["object", "s3", "blob", "bucket", "gcs", "cloud storage", "standard storage"],
    },
    {
        "key": "archive_storage",
        "sku": "B91633",
        "description": "Archive Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.0026,
        "category": "Storage",
        "notes": "Maps AWS Glacier/Deep Archive, Azure Archive Blob, GCP Archive/Coldline, and backup archive tiers.",
        "keywords": ["archive", "glacier", "deep archive", "coldline", "cold storage", "backup archive"],
    },
    {
        "key": "object_storage_requests",
        "sku": "B91627",
        "description": "Object Storage - Requests",
        "unit": "10,000 requests",
        "rate": 0.0034,
        "category": "Storage",
        "notes": "Maps S3/Blob/GCS request rows when a bill provides request counts.",
        "keywords": ["request", "api request", "put", "get", "list", "object request"],
    },
]

FULL_SERVICE_CATALOG_ITEMS = [
    {
        "key": "compute_ocpu_hours",
        "sku": SHAPE_LOOKUP[DEFAULT_SHAPE_KEY]["computeSku"],
        "description": "OCPU-hr rate (Compute)",
        "unit": "OCPU-hour",
        "rate": SHAPE_LOOKUP[DEFAULT_SHAPE_KEY]["computeRate"],
        "category": "Compute",
        "notes": "Maps source rows that provide OCPU-hours, vCPU-hours, or CPU core-hours.",
        "keywords": ["ocpu", "vcpu", "cpu hour", "cpu-hour", "core hour", "core-hour", "compute"],
    },
    {
        "key": "memory_gb_hours",
        "sku": SHAPE_LOOKUP[DEFAULT_SHAPE_KEY]["memorySku"],
        "description": "Memory GB-hr rate",
        "unit": "GB-hour",
        "rate": SHAPE_LOOKUP[DEFAULT_SHAPE_KEY]["memoryRate"],
        "category": "Compute",
        "notes": "Maps source rows that provide memory GB-hours.",
        "keywords": ["memory", "ram", "gb hour", "gb-hour", "gib hour", "gib-hour"],
    },
    {
        "key": "block_volume_storage",
        "sku": "B91961",
        "description": "Block Volume Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.0255,
        "category": "Storage",
        "notes": "Maps AWS EBS, Azure Managed Disk, GCP Persistent Disk, VMware disks, SAN, and generic block volumes.",
        "keywords": ["ebs", "managed disk", "persistent disk", "block", "volume", "san", "disk", "rds storage", "database storage"],
    },
    {
        "key": "file_storage",
        "sku": "B89057",
        "description": "File Storage (GB-mo)",
        "unit": "GB-month",
        "rate": 0.3000,
        "category": "Storage",
        "notes": "Maps AWS EFS, Azure Files, GCP Filestore, NFS, SMB, NAS, and shared file systems.",
        "keywords": ["efs", "azure files", "filestore", "file share", "nfs", "smb", "nas", "file storage"],
    },
    *FULL_SERVICE_RATE_ITEMS,
]
FULL_SERVICE_RATE_BY_KEY = {item["key"]: item for item in FULL_SERVICE_CATALOG_ITEMS}

OCI_OFFICIAL_REFERENCES = [
    {
        "name": "Oracle cross-cloud service mapping",
        "url": "https://www.oracle.com/a/ocom/docs/ocimapping/ocimapping.html",
        "use": "Comparable AWS, Azure, and GCP services should be mapped to the closest OCI service family before pricing.",
    },
    {
        "name": "OCI price list",
        "url": "https://www.oracle.com/cloud/price-list/",
        "use": "OCI pricing is based on Oracle product meters such as OCPU-hour, GB-hour, GB-month, load balancer hour, bandwidth, requests, transactions, or ECPU/OCPU units.",
    },
]

OCI_SOURCE_SERVICE_MAPPINGS = [
    {
        "sourceServices": ["AWS EC2", "Azure Virtual Machines", "Google Compute Engine"],
        "ociServiceCategory": "Compute",
        "ociComparableServices": ["OCI Virtual Machine Instances", "OCI Bare Metal Instances"],
        "metering": "Map vCPU/core-hour usage to OCPU-hour using 2 vCPU = 1 OCPU for x86 when the bill is vCPU-based. Map memory usage to GB-hour when memory is separately metered.",
        "catalogKeys": ["compute_ocpu_hours", "memory_gb_hours"],
    },
    {
        "sourceServices": ["AWS S3", "Azure Blob Storage", "Google Cloud Storage"],
        "ociServiceCategory": "Storage",
        "ociComparableServices": ["OCI Object Storage", "OCI Archive Storage"],
        "metering": "Standard/hot object capacity maps to GB-month. Archive, Glacier, Deep Archive, Archive Blob, Coldline, and similar archive/cold tiers map to archive GB-month. Request meters remain request counts and are priced per 10,000 requests where available.",
        "catalogKeys": ["object_storage_standard", "archive_storage", "object_storage_requests"],
    },
    {
        "sourceServices": ["AWS EBS", "Azure Managed Disks", "Google Persistent Disk"],
        "ociServiceCategory": "Storage",
        "ociComparableServices": ["OCI Block Volumes"],
        "metering": "Capacity maps to block volume GB-month. Performance, IOPS, throughput, and provisioned VPU-style meters require review unless a matching OCI performance meter is available.",
        "catalogKeys": ["block_volume_storage"],
    },
    {
        "sourceServices": ["AWS EFS", "Azure Files", "Google Filestore", "NAS", "NFS", "SMB"],
        "ociServiceCategory": "Storage",
        "ociComparableServices": ["OCI File Storage"],
        "metering": "Capacity maps to file storage GB-month. Premium performance or replication meters should be reviewed.",
        "catalogKeys": ["file_storage"],
    },
    {
        "sourceServices": ["AWS Elastic Load Balancing", "Azure Load Balancer", "Azure Application Gateway", "Google Cloud Load Balancing"],
        "ociServiceCategory": "Networking",
        "ociComparableServices": ["OCI Load Balancer", "OCI Web Application Firewall"],
        "metering": "Map base/load-balancer-hours and bandwidth/throughput meters separately. If no matching local rate-card item exists, preserve the target service and mark the row for review.",
        "catalogKeys": [],
    },
    {
        "sourceServices": ["AWS Data Transfer", "Azure Bandwidth", "Google Network Egress", "Cloud CDN egress"],
        "ociServiceCategory": "Networking",
        "ociComparableServices": ["OCI Networking outbound data transfer", "OCI FastConnect"],
        "metering": "Map egress to data transfer GB where regional direction and tier are clear. Mark inter-region, internet, CDN, or private-connectivity rows for review when the target meter is ambiguous.",
        "catalogKeys": [],
    },
    {
        "sourceServices": ["AWS RDS", "AWS Aurora", "Azure SQL Database", "Azure Database for PostgreSQL", "Azure Database for MySQL", "Google Cloud SQL", "AlloyDB"],
        "ociServiceCategory": "Oracle Databases",
        "ociComparableServices": ["Oracle Autonomous AI Transaction Processing", "Oracle MySQL Database Service", "OCI Database with PostgreSQL", "Oracle Base Database Service"],
        "metering": "Database compute commonly maps to OCPU/ECPU hours and storage to GB-month, but engine, license, HA, backup, and deployment model change the target OCI product. Mark for review unless the source row gives a clear Oracle-compatible database target.",
        "catalogKeys": [],
    },
    {
        "sourceServices": ["AWS Lambda", "Azure Functions", "Google Cloud Functions", "Cloud Run functions"],
        "ociServiceCategory": "Containers and Functions",
        "ociComparableServices": ["OCI Functions"],
        "metering": "Function pricing separates invocations from execution duration such as GB-seconds. Keep invocation and duration rows separate and mark for review if the local catalog lacks the meter.",
        "catalogKeys": [],
    },
    {
        "sourceServices": ["AWS EKS", "Azure AKS", "Google GKE"],
        "ociServiceCategory": "Containers and Functions",
        "ociComparableServices": ["OCI Kubernetes Engine", "OCI Registry"],
        "metering": "Cluster management, worker compute, registry, storage, and network rows should be separated. Underlying VM/storage rows can map to compute/storage meters; cluster management rows need review unless a local catalog meter exists.",
        "catalogKeys": ["compute_ocpu_hours", "memory_gb_hours", "block_volume_storage"],
    },
]

OCI_METERING_GUIDANCE = [
    "OCI price-list pages show both vCPU comparison prices and OCPU prices, but OCI products bill in OCPU units; for common x86 shapes, 1 OCPU is equivalent to 2 vCPUs.",
    "Do not turn source-cloud monthly cost into an OCI unit rate. Use source cost only for comparison and prioritization.",
    "Preserve separate bill lines when the source has separate meters, such as compute hours, memory hours, storage capacity, performance units, requests, and network transfer.",
    "Convert storage capacity to GB-month when possible: TB-month x 1024, MB-month / 1024, GB-hour / 730, byte-hours / 1024^3 / 730.",
    "Convert vCPU-hour to OCPU-hour by multiplying by 0.5 when the source meter is vCPU/core based. Leave OCPU-hour unchanged.",
    "Request meters should retain raw request counts; pricing logic converts to 10,000-request units when the OCI product uses that meter.",
    "When the local catalog has no exact OCI price-list item, still populate OCI service/product labels and mark the row as Needs review rather than forcing a bad price.",
]


def load_local_env():
    env_path = ROOT / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = (
        str(value)
        .replace("\ufb00", "ff")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\ufb03", "ffi")
        .replace("\ufb04", "ffl")
        .replace("\n", " ")
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def make_key(label, seen):
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "column"
    key = base
    idx = 2
    while key in seen:
        key = f"{base}_{idx}"
        idx += 1
    seen.add(key)
    return key


def clean_cell(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 4)
    return clean_text(value)


def spreadsheet_cpu_label(label):
    text = normalize(label)
    if not text:
        return False
    if any(term in text for term in ["chipset", "processor family", "cpu type", "architecture", "model"]):
        return False
    return any(
        term in text
        for term in [
            "vcpu",
            "vcpus",
            "v cpu",
            "virtual cpu",
            "cpu vcpu",
            "cpu cores",
            "number of cpu",
            "num cpu",
            "cpu count",
            "cores per server",
            "core count",
        ]
    )


def spreadsheet_memory_label(label):
    text = normalize(label)
    if not text:
        return False
    if any(term in text for term in ["storage", "disk", "iops", "swap"]):
        return False
    return any(term in text for term in ["ram", "memory", "mem gb", "gb ram"])


def spreadsheet_storage_label(label):
    text = normalize(label)
    if not text:
        return False
    if any(term in text for term in ["iops", "cpu", "ocpu", "vcpu", "memory", "ram", "load balancer"]):
        return False
    if header_is_bare_disk_count(text):
        return False
    return any(
        term in text
        for term in [
            "storage",
            "database size",
            "db size",
            "allocated",
            "disk gb",
            "disk size",
            "disk capacity",
            "volume size",
            "data size",
        ]
    )


def ocpu_review_label(label):
    text = normalize(label)
    prefix = "Database Details" if any(term in text for term in ["database", " db ", "db cpu", "db cores"]) else "Application Details"
    return f"{prefix}: OCPUs"


def memory_review_label(label):
    text = normalize(label)
    prefix = "Database Details" if any(term in text for term in ["database", " db ", "db memory", "db ram"]) else "Application Details"
    return f"{prefix}: Memory per server (GB)"


def to_number(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return default
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def to_gb(value, default=0.0):
    number = to_number(value, default)
    text = normalize(value)
    if not text:
        return default
    if re.search(r"(?:^|\d|\s)tbs?(?:$|\s)|terabytes?", text):
        return number * 1024
    if re.search(r"(?:^|\d|\s)mbs?(?:$|\s)|megabytes?", text):
        return number / 1024
    if re.search(r"(?:^|\d|\s)kbs?(?:$|\s)|kilobytes?", text):
        return number / (1024 * 1024)
    return number


def header_has_database_signal(label):
    text = normalize(label)
    return bool(re.search(r"\b(database|db|sql|oracle|postgres|mysql|mssql|rds)\b", text))


def header_has_storage_capacity_signal(label):
    text = normalize(label)
    return any(
        term in text
        for term in [
            "storage",
            "allocated",
            "capacity",
            "disk gb",
            "disk size",
            "disk capacity",
            "volume size",
            "provisioned",
            "used gb",
            "total gb",
        ]
    )


def header_is_bare_disk_count(label):
    text = normalize(label)
    if not text:
        return False
    if header_has_storage_capacity_signal(text):
        return False
    return text in {"disk", "disks", "disk count", "number of disks", "num disks", "drive count", "drives"}


def column_numeric_profile(raw, col_idx, data_start_row=None, max_rows=80):
    start_idx = max(0, int(to_number(data_start_row, 0) or 1) - 1)
    numbers = []
    end_idx = min(len(raw.index), start_idx + max_rows)
    for row_idx in range(start_idx, end_idx):
        if col_idx >= len(raw.columns):
            continue
        value = raw.iat[row_idx, col_idx]
        if clean_text(value) == "":
            continue
        number = to_number(value, None)
        if number is not None:
            numbers.append(number)
    if not numbers:
        return {"count": 0, "max": 0, "p95": 0, "integerRatio": 0, "smallIntegerRatio": 0}
    ordered = sorted(abs(number) for number in numbers)
    p95_index = min(len(ordered) - 1, int(math.ceil(len(ordered) * 0.95)) - 1)
    integer_count = sum(1 for number in numbers if float(number).is_integer())
    small_integer_count = sum(1 for number in numbers if float(number).is_integer() and 0 <= abs(number) <= 64)
    return {
        "count": len(numbers),
        "max": max(ordered),
        "p95": ordered[p95_index],
        "integerRatio": integer_count / len(numbers),
        "smallIntegerRatio": small_integer_count / len(numbers),
    }


def column_looks_like_disk_count(raw, col_idx, label, data_start_row=None):
    if not header_is_bare_disk_count(label):
        return False
    profile = column_numeric_profile(raw, col_idx, data_start_row)
    if profile["count"] < 3:
        return True
    return profile["smallIntegerRatio"] >= 0.8 and profile["p95"] <= 32


def storage_mapping_disallowed(raw, col_idx, key, label, data_start_row=None):
    if key not in {
        "application_details_local_storage_gb",
        "application_details_shared_storage_gb",
        "database_details_total_allocated_storage_gb",
    }:
        return False
    return column_looks_like_disk_count(raw, col_idx, label, data_start_row)


def compact_number(value):
    if value == "":
        return ""
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 4)


def normalize_inventory_value(key, value):
    if clean_text(value) == "":
        return ""
    if key in CPU_FIELD_KEYS:
        if key == "resource_ocpus":
            return compact_number(to_number(value))
        return compact_number(to_number(value) / 2)
    if key in SIZE_FIELD_KEYS:
        return compact_number(to_gb(value))
    if key in NUMERIC_FIELD_KEYS:
        return compact_number(to_number(value))
    return clean_cell(value)


def parse_json_cell(value):
    text = clean_text(value)
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def add_json_pair(pairs, key, value):
    key_text = clean_text(key)
    value_text = clean_cell(value)
    if key_text and value_text != "":
        pairs[key_text] = value_text


def flatten_json_tags(value):
    parsed = parse_json_cell(value)
    if parsed is None:
        return {}

    pairs = {}

    def visit(node, prefix=""):
        if isinstance(node, dict):
            tag_key = node.get("key") or node.get("Key") or node.get("tagKey")
            tag_value = node.get("value") or node.get("Value") or node.get("tagValue")
            tag_text = node.get("tag") or node.get("Tag")
            if tag_key is not None and tag_value is not None:
                add_json_pair(pairs, tag_key, tag_value)
            if tag_text and "=" in clean_text(tag_text):
                left, right = clean_text(tag_text).split("=", 1)
                add_json_pair(pairs, left, tag_value if tag_value is not None else right)

            for key, child in node.items():
                child_key = clean_text(key)
                path = f"{prefix}.{child_key}" if prefix else child_key
                if isinstance(child, (dict, list)):
                    visit(child, path)
                elif child_key not in {"key", "Key", "value", "Value", "tag", "Tag"}:
                    add_json_pair(pairs, path, child)
        elif isinstance(node, list):
            for child in node:
                visit(child, prefix)

    visit(parsed)
    return pairs


def json_key_match_score(candidate, target):
    candidate_norm = normalize(candidate)
    target_norm = normalize(target)
    if not candidate_norm or not target_norm:
        return 0
    if candidate_norm == target_norm:
        return 100
    if candidate_norm.endswith(f" {target_norm}") or candidate_norm.endswith(target_norm):
        return 80
    if target_norm in candidate_norm:
        return 60
    if candidate_norm in target_norm and len(candidate_norm) >= 3:
        return 40
    return 0


def value_from_json_cell(value, json_key):
    target = clean_text(json_key)
    if not target:
        return ""
    pairs = flatten_json_tags(value)
    if not pairs:
        return ""
    best_key = ""
    best_score = 0
    for key in pairs:
        score = json_key_match_score(key, target)
        if score > best_score:
            best_key = key
            best_score = score
    return pairs.get(best_key, "") if best_score >= 40 else ""


def summarize_json_cell(value, max_items=8):
    pairs = flatten_json_tags(value)
    if not pairs:
        return None
    return {
        "keys": list(pairs.keys())[:max_items],
        "preview": {key: pairs[key] for key in list(pairs.keys())[:max_items]},
    }


def json_column_header(raw, col_idx):
    parts = []
    for row_idx in range(min(8, len(raw.index))):
        value = raw.iat[row_idx, col_idx]
        text = clean_text(value)
        if text and parse_json_cell(value) is None and text not in parts:
            parts.append(text)
    return " ".join(parts[:3])


def canonical_fields_payload(full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM):
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "sourceColumn": None,
            "important": True,
        }
        for field in inventory_fields(full_service_beta, intake_mode)
    ]


def canonical_field_prompt(full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM):
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "description": field["description"],
            "aliases": field["aliases"],
        }
        for field in inventory_fields(full_service_beta, intake_mode)
    ]


def resolve_shape(shape_key=None):
    return SHAPE_LOOKUP.get(shape_key or DEFAULT_SHAPE_KEY, SHAPE_LOOKUP[DEFAULT_SHAPE_KEY])


def price_catalog_payload():
    return [
        {
            "key": item["key"],
            "sku": item["sku"],
            "description": item["description"],
            "unit": item["unit"],
            "rate": item["rate"],
            "category": item["category"],
            "keywords": item["keywords"],
        }
        for item in FULL_SERVICE_CATALOG_ITEMS
    ]


def build_rate_card(shape_key=None, full_service_beta=False):
    shape = resolve_shape(shape_key)
    items = [
        {
            "sku": shape.get("computeSku", "B97384"),
            "description": "OCPU-hr rate (Compute)",
            "unit": "OCPU-hour",
            "rate": shape["computeRate"],
            "notes": f"{shape['label']} OCPU-hours x 730 hrs/mo",
        },
        {
            "sku": shape.get("memorySku", "B97385"),
            "description": "Memory GB-hr rate",
            "unit": "GB-hour",
            "rate": shape["memoryRate"],
            "notes": f"{shape['label']} GB-hours x 730 hrs/mo",
        },
        *[item.copy() for item in STORAGE_RATE_ITEMS],
        WINDOWS_LICENSE_ITEM.copy(),
    ]
    if full_service_beta:
        seen_skus = {item["sku"] for item in items}
        for item in FULL_SERVICE_RATE_ITEMS:
            if item["sku"] in seen_skus:
                continue
            items.append(
                {
                    "sku": item["sku"],
                    "description": item["description"],
                    "unit": item["unit"],
                    "rate": item["rate"],
                    "notes": item["notes"],
                }
            )
            seen_skus.add(item["sku"])
    return items


def shape_payload(shape_key=None, full_service_beta=False):
    shape = resolve_shape(shape_key)
    return {
        "key": shape["key"],
        "label": shape["label"],
        "shortLabel": shape["shortLabel"],
        "family": shape["family"],
        "processorVendor": shape.get("processorVendor", "amd"),
        "summary": shape["summary"],
        "accent": shape["accent"],
        "computeSku": shape.get("computeSku", "B97384"),
        "memorySku": shape.get("memorySku", "B97385"),
        "computeRate": shape["computeRate"],
        "memoryRate": shape["memoryRate"],
        "hoursPerMonth": HOURS_PER_MONTH,
        "rateCard": build_rate_card(shape["key"], full_service_beta),
    }


def all_shape_payloads(full_service_beta=False):
    return [shape_payload(shape["key"], full_service_beta) for shape in SHAPE_DEFINITIONS]


def pick_sheet(excel_file):
    names = excel_file.sheet_names
    for name in names:
        if normalize(name) == "current app db infra details":
            return name
    best_name = names[0]
    best_score = -1
    for name in names:
        raw = pd.read_excel(excel_file, sheet_name=name, header=None, dtype=object)
        text = normalize(
            " ".join(
                clean_text(raw.iat[row_idx, col_idx])
                for row_idx in range(min(30, len(raw.index)))
                for col_idx in range(min(20, len(raw.columns)))
                if clean_text(raw.iat[row_idx, col_idx])
            )
        )
        score = 0
        for term, weight in {
            "server vm inventory": 10,
            "server vm name": 8,
            "cpu vcpu": 8,
            "vcpu": 6,
            "ram gb": 6,
            "memory": 5,
            "number of cpu": 6,
            "number of servers": 5,
        }.items():
            if term in text:
                score += weight
        numeric_cells = 0
        for row_idx in range(min(80, len(raw.index))):
            row_text = normalize(" ".join(clean_text(value) for value in raw.iloc[row_idx].tolist()))
            if spreadsheet_cpu_label(row_text) or spreadsheet_memory_label(row_text):
                score += 4
            numeric_cells += sum(1 for value in raw.iloc[row_idx].tolist() if to_number(value, 0))
        score += min(12, numeric_cells // 8)
        if score > best_score:
            best_name = name
            best_score = score
    return best_name


def inventory_header_score(values, next_values=None):
    cells = [clean_text(value) for value in values if clean_text(value)]
    text = normalize(" ".join(cells))
    if not text:
        return 0
    score = min(10, len(cells))
    terms = {
        "application name": 12,
        "server vm name": 14,
        "server name": 10,
        "vm name": 10,
        "host name": 10,
        "environment": 6,
        "env": 4,
        "operating system": 8,
        "os version": 7,
        "cpu vcpu": 14,
        "vcpu": 12,
        "number of cpu": 12,
        "cpu cores": 10,
        "ram gb": 12,
        "memory per server": 12,
        "memory": 8,
        "local disk": 8,
        "storage": 6,
    }
    for term, weight in terms.items():
        if term in text:
            score += weight
    if "customer response" in text and "guidance" in text:
        score -= 12
    if "purpose capture" in text or "questionnaire" in text:
        score -= 10
    if next_values is not None:
        next_text = normalize(" ".join(clean_text(value) for value in next_values if clean_text(value)))
        if next_text and not any(term in next_text for term in ["guidance examples", "purpose capture"]):
            score += 3
        numeric_next = sum(1 for value in next_values if to_number(value, 0))
        score += min(8, numeric_next)
    return score


def detect_header_rows(raw):
    sample_rows = min(60, len(raw.index))
    best_score = -1
    header_row = 0
    for idx in range(sample_rows):
        values = raw.iloc[idx].tolist()
        next_values = raw.iloc[idx + 1].tolist() if idx + 1 < len(raw.index) else []
        score = inventory_header_score(values, next_values)
        if score > best_score:
            best_score = score
            header_row = idx
    group_row = max(0, header_row - 1)
    return group_row, header_row, header_row + 1


def is_important(label):
    text = normalize(label)
    terms = [
        "application name",
        "environment",
        "application type",
        "number of servers",
        "number of database servers",
        "number of cpu cores per server",
        "memory per server gb",
        "local storage gb",
        "shared storage gb",
        "database type",
        "database size gb",
        "total allocated storage gb",
        "total storage gb",
        "storage iops",
    ]
    return any(term in text for term in terms)


def build_fields(raw, group_row, header_row):
    sections = {"application details", "database details", "oci details"}
    fields = []
    seen = set()
    current_section = ""

    for col_idx in range(len(raw.columns)):
        top = clean_text(raw.iat[group_row, col_idx]) if group_row < len(raw.index) else ""
        sub = clean_text(raw.iat[header_row, col_idx]) if header_row < len(raw.index) else ""
        top_norm = normalize(top)

        if top_norm in sections:
            current_section = top
            label = f"{current_section}: {sub}" if sub else current_section
        elif sub:
            label = f"{current_section}: {sub}" if current_section else sub
        elif top:
            label = top
        else:
            label = f"Column {col_idx + 1}"

        label = clean_text(label)
        fields.append(
            {
                "key": make_key(label, seen),
                "label": label,
                "sourceColumn": col_idx + 1,
                "important": is_important(label),
            }
        )

    return fields


def meaningful_inventory_value(value):
    text = normalize(value)
    return bool(text and text not in {"na", "n a", "none", "null", "tbd", "unknown"})


def rule_based_row_has_inventory_signal(row, fields):
    has_application = False
    has_environment = False
    has_descriptive_detail = False
    has_resource = False

    for field in fields:
        value = row.get(field["key"])
        if not meaningful_inventory_value(value):
            continue
        label = normalize(field.get("label"))
        if "application name" in label or label in {"application", "app name"}:
            has_application = True
        elif "environment" in label or label == "env":
            has_environment = True
        elif (
            "ocpu" in label
            or spreadsheet_cpu_label(label)
            or spreadsheet_memory_label(label)
            or spreadsheet_storage_label(label)
            or "number of servers" in label
            or "number of database servers" in label
        ):
            has_resource = True
        elif any(term in label for term in ["application type", "database type", "server name", "host name", "description"]):
            has_descriptive_detail = True

    if not has_application:
        return False
    return has_resource or has_environment or has_descriptive_detail


def parse_workbook_rule_based(path, full_service_beta=False):
    excel_file = pd.ExcelFile(path)
    sheet = pick_sheet(excel_file)
    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    group_row, header_row, data_start = detect_header_rows(raw)
    fields = build_fields(raw, group_row, header_row)
    cpu_field_keys = set()
    memory_field_keys = set()
    storage_field_keys = set()
    for field in fields:
        if spreadsheet_cpu_label(field["label"]):
            cpu_field_keys.add(field["key"])
            field["label"] = ocpu_review_label(field["label"])
        elif spreadsheet_memory_label(field["label"]):
            memory_field_keys.add(field["key"])
            field["label"] = memory_review_label(field["label"])
        elif spreadsheet_storage_label(field["label"]):
            storage_field_keys.add(field["key"])

    rows = []
    for raw_idx in range(data_start, len(raw.index)):
        values = raw.iloc[raw_idx].tolist()
        if not any(clean_text(value) for value in values):
            continue
        row = {"__id": f"row-{raw_idx + 1}", "__sourceRow": raw_idx + 1, "__approved": True}
        for col_idx, field in enumerate(fields):
            value = clean_cell(values[col_idx]) if col_idx < len(values) else ""
            if field["key"] in cpu_field_keys and clean_text(value) != "":
                value = compact_number(to_number(value) / 2)
            elif field["key"] in memory_field_keys and clean_text(value) != "":
                value = compact_number(to_gb(value))
            elif field["key"] in storage_field_keys and clean_text(value) != "":
                value = compact_number(to_gb(value))
            row[field["key"]] = value
        if rule_based_row_has_inventory_signal(row, fields):
            rows.append(row)

    return {
        "fileName": Path(path).name,
        "sheetName": sheet,
        "sheets": excel_file.sheet_names,
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY, full_service_beta),
        "rateCards": all_shape_payloads(full_service_beta),
        "fullServiceCatalog": price_catalog_payload(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY, full_service_beta),
        "metadata": {
            "headerRow": header_row + 1,
            "groupRow": group_row + 1,
            "dataStartRow": data_start + 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
            "parser": "rule-based",
            "intakeMode": INTAKE_MODE_ON_PREM,
            "fullServiceBeta": bool(full_service_beta),
        },
    }


def workbook_digest(path):
    excel_file = pd.ExcelFile(path)
    sheets = []
    for sheet in excel_file.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
        max_rows = min(45, len(raw.index))
        max_cols = min(35, len(raw.columns))
        sample_rows = []
        row_density = []
        json_columns = {}

        for row_idx in range(min(100, len(raw.index))):
            values = raw.iloc[row_idx].tolist()
            non_blank = [clean_text(value) for value in values if clean_text(value)]
            if non_blank:
                row_density.append(
                    {
                        "row": row_idx + 1,
                        "nonBlank": len(non_blank),
                        "preview": non_blank[:12],
                    }
                )

        for row_idx in range(max_rows):
            cells = []
            for col_idx in range(max_cols):
                value = clean_text(raw.iat[row_idx, col_idx])
                if value:
                    cell = {"column": col_idx + 1, "value": value[:140]}
                    json_summary = summarize_json_cell(value)
                    if json_summary:
                        cell["jsonKeys"] = json_summary["keys"]
                        cell["jsonPreview"] = json_summary["preview"]
                        column_info = json_columns.setdefault(
                            col_idx + 1,
                            {
                                "column": col_idx + 1,
                                "sampleRows": [],
                                "keys": {},
                            },
                        )
                        column_info["sampleRows"].append(
                            {
                                "row": row_idx + 1,
                                "preview": json_summary["preview"],
                            }
                        )
                        for key, item in json_summary["preview"].items():
                            column_info["keys"].setdefault(key, clean_text(item)[:80])
                    cells.append(cell)
            if cells:
                sample_rows.append({"row": row_idx + 1, "cells": cells[:24]})

        json_column_summaries = []
        for col_idx, info in json_columns.items():
            json_column_summaries.append(
                {
                    "column": col_idx,
                    "header": json_column_header(raw, col_idx - 1),
                    "keys": list(info["keys"].keys())[:30],
                    "sampleValues": dict(list(info["keys"].items())[:12]),
                    "sampleRows": info["sampleRows"][:3],
                }
            )

        sheets.append(
            {
                "name": sheet,
                "rowCount": int(len(raw.index)),
                "columnCount": int(len(raw.columns)),
                "sampleRows": sample_rows,
                "jsonColumns": json_column_summaries,
                "likelyHeaderRows": sorted(row_density, key=lambda item: item["nonBlank"], reverse=True)[:8],
            }
        )

    return {"sheets": sheets}


def carried_section_label(raw, row_idx, col_idx):
    sections = {"application details", "database details", "oci details"}
    for scan_idx in range(col_idx, -1, -1):
        candidate = clean_text(raw.iat[row_idx, scan_idx])
        if normalize(candidate) in sections:
            return candidate
    return ""


def header_label(raw, header_rows, col_idx):
    parts = []
    for row_number in header_rows:
        row_idx = int(row_number) - 1
        if 0 <= row_idx < len(raw.index):
            part = clean_text(raw.iat[row_idx, col_idx])
            if not part:
                part = carried_section_label(raw, row_idx, col_idx)
            if part and part not in parts:
                parts.append(part)
    return " ".join(parts)


def alias_score(label, field):
    label_norm = normalize(label)
    if not label_norm:
        return 0
    if field["key"] == "application_name" and "database" in label_norm and "application" not in label_norm:
        return 0
    if header_is_bare_disk_count(label_norm) and field["key"] in {
        "application_details_local_storage_gb",
        "application_details_shared_storage_gb",
        "database_details_total_allocated_storage_gb",
    }:
        return 0
    aliases = [field["label"], *field["aliases"]]
    score = 0
    for alias in aliases:
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if label_norm == alias_norm:
            score = max(score, 100 + len(alias_norm))
        elif alias_norm in label_norm:
            score = max(score, 60 + len(alias_norm))
        elif label_norm in alias_norm and len(label_norm) >= 4:
            score = max(score, 30 + len(label_norm))

    is_database = any(term in label_norm for term in ["database", "db ", " db", "sql", "oracle db"])
    field_is_database = field["key"].startswith("database_details")
    if is_database and field_is_database:
        score += 14
    elif is_database and not field_is_database:
        score -= 12
    elif field_is_database:
        score -= 18

    is_shared = any(term in label_norm for term in ["shared", "nas", "nfs", "file"])
    if is_shared and field["key"] == "application_details_shared_storage_gb":
        score += 16
    elif is_shared and field["key"] == "application_details_local_storage_gb":
        score -= 10

    return score


def infer_column_mappings(raw, header_rows, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM, data_start_row=None):
    mappings = {}
    for col_idx in range(len(raw.columns)):
        label = header_label(raw, header_rows, col_idx)
        best = None
        best_score = 0
        for field in inventory_fields(full_service_beta, intake_mode):
            if storage_mapping_disallowed(raw, col_idx, field["key"], label, data_start_row):
                continue
            score = alias_score(label, field)
            if score > best_score:
                best = field
                best_score = score
        if best and best_score >= 45:
            existing = mappings.get(best["key"])
            if existing and existing.get("_score", 0) >= best_score:
                continue
            mappings[best["key"]] = {
                "canonicalKey": best["key"],
                "sourceColumn": col_idx + 1,
                "sourceHeader": label,
                "confidence": min(0.98, best_score / 130),
                "_score": best_score,
            }
    return mappings


JSON_TAG_FIELD_ALIASES = {
    "application_name": ["Name", "name", "appName", "application", "applicationName", "appId", "appID"],
    "environment": ["environment", "env", "stage", "lifecycle"],
    "application_details": ["role", "description", "appId", "costCenter", "owner"],
    "application_details_application_version": ["applicationVersion", "appVersion", "version", "release"],
    "application_details_operating_system": ["os", "operatingSystem", "operating_system", "platform"],
}


def infer_json_mappings(raw, header_rows, data_start_row):
    mappings = {}
    start_idx = max(0, data_start_row - 1)
    end_idx = min(len(raw.index), start_idx + 30)
    for col_idx in range(len(raw.columns)):
        label = header_label(raw, header_rows, col_idx)
        column_pairs = {}
        for row_idx in range(start_idx, end_idx):
            for key, value in flatten_json_tags(raw.iat[row_idx, col_idx]).items():
                column_pairs.setdefault(key, clean_text(value))
        if not column_pairs:
            continue

        for canonical_key, aliases in JSON_TAG_FIELD_ALIASES.items():
            if canonical_key in mappings:
                continue
            best_key = ""
            best_score = 0
            for candidate in column_pairs:
                for alias in aliases:
                    score = json_key_match_score(candidate, alias)
                    if score > best_score:
                        best_key = candidate
                        best_score = score
            if best_score >= 60:
                mappings[canonical_key] = {
                    "canonicalKey": canonical_key,
                    "sourceColumn": col_idx + 1,
                    "sourceHeader": label,
                    "jsonKey": best_key,
                    "confidence": min(0.95, best_score / 100),
                    "transform": f"Read '{best_key}' from JSON/tag data.",
                }
    return mappings


def validated_column_mappings(raw, header_rows, mappings, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM, data_start_row=None):
    validated = {}
    field_lookup = {field["key"]: field for field in inventory_fields(full_service_beta, intake_mode)}
    for key, mapping in mappings.items():
        field = field_lookup.get(key)
        if not field:
            continue
        source_column = int(to_number(mapping.get("sourceColumn"), 0))
        if source_column <= 0:
            continue
        actual_header = header_label(raw, header_rows, source_column - 1) or clean_text(mapping.get("sourceHeader"))
        if key == "application_details_number_of_servers" and column_looks_like_disk_count(
            raw, source_column - 1, actual_header, data_start_row
        ):
            continue
        if storage_mapping_disallowed(raw, source_column - 1, key, actual_header, data_start_row):
            continue
        if key == "database_details_total_allocated_storage_gb" and not header_has_database_signal(actual_header):
            continue
        has_json_source = clean_text(mapping.get("jsonKey") or mapping.get("jsonPath"))
        if has_json_source:
            json_aliases = [field["label"], *field["aliases"], *JSON_TAG_FIELD_ALIASES.get(key, [])]
            if max((json_key_match_score(has_json_source, alias) for alias in json_aliases), default=0) < 40:
                continue
        if actual_header and not has_json_source and alias_score(actual_header, field) < 35:
            continue
        validated[key] = {
            **mapping,
            "sourceHeader": actual_header,
            "sourceColumn": source_column,
        }
    return validated


def normalize_workbook_plan(plan, excel_file, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM):
    if not isinstance(plan, dict):
        return None
    sheet_name = clean_text(plan.get("sheetName"))
    if sheet_name not in excel_file.sheet_names:
        normalized_target = normalize(sheet_name)
        matches = [name for name in excel_file.sheet_names if normalize(name) == normalized_target]
        sheet_name = matches[0] if matches else ""
    if not sheet_name:
        return None

    header_rows = plan.get("headerRows") or plan.get("headerRow") or []
    if isinstance(header_rows, (str, int, float)):
        header_rows = [header_rows]
    header_rows = [int(to_number(item)) for item in header_rows if to_number(item)]
    header_rows = sorted({row for row in header_rows if row > 0})

    data_start = int(to_number(plan.get("dataStartRow"), 0))
    if data_start <= 0 and header_rows:
        data_start = max(header_rows) + 1
    if data_start <= 0:
        data_start = 2

    data_end = int(to_number(plan.get("dataEndRow"), 0))
    raw_mappings = plan.get("columnMappings", [])
    if isinstance(raw_mappings, dict):
        raw_mappings = [
            {"canonicalKey": key, **value} if isinstance(value, dict) else {"canonicalKey": key, "sourceColumn": value}
            for key, value in raw_mappings.items()
        ]

    mappings = {}
    field_lookup = {field["key"]: field for field in inventory_fields(full_service_beta, intake_mode)}
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("canonicalKey") or item.get("key"))
        source_column = int(to_number(item.get("sourceColumn"), 0))
        if key in field_lookup and source_column > 0:
            mappings[key] = {
                "canonicalKey": key,
                "sourceColumn": source_column,
                "sourceHeader": clean_text(item.get("sourceHeader")),
                "jsonKey": clean_text(item.get("jsonKey") or item.get("tagKey")),
                "jsonPath": clean_text(item.get("jsonPath")),
                "confidence": to_number(item.get("confidence"), 0),
                "transform": clean_text(item.get("transform")),
            }

    return {
        "sheetName": sheet_name,
        "headerRows": header_rows,
        "dataStartRow": data_start,
        "dataEndRow": data_end or None,
        "serverGrain": normalize(plan.get("serverGrain")) or "unknown",
        "confidence": to_number(plan.get("confidence"), 0),
        "columnMappings": mappings,
        "notes": plan.get("notes", []),
    }


def should_keep_inventory_row(row):
    identity = clean_text(row.get("application_name")) or clean_text(row.get("environment"))
    resources = [
        to_number(row.get("application_details_number_of_servers")),
        to_number(row.get("application_details_number_of_cpu_cores_per_server")),
        to_number(row.get("application_details_memory_per_server_gb")),
        to_number(row.get("application_details_local_storage_gb")),
        to_number(row.get("database_details_number_of_database_servers")),
        to_number(row.get("database_details_number_of_cpu_cores_per_server")),
        to_number(row.get("database_details_memory_per_server_gb")),
        to_number(row.get("database_details_total_allocated_storage_gb")),
    ]
    populated_fields = sum(
        1
        for field in CANONICAL_FIELD_BY_KEY.values()
        if clean_text(row.get(field["key"])) not in {"", "0", "0.0"}
    )
    full_service_signal = any(clean_text(row.get(key)) for key in SOURCE_SERVICE_FIELD_KEYS)
    resource_signal = any(value for value in resources)
    if full_service_signal:
        return True
    if not identity:
        return False
    return bool(resource_signal or populated_fields >= 2)


def parse_workbook_from_plan(path, plan, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM):
    excel_file = pd.ExcelFile(path)
    raw = pd.read_excel(path, sheet_name=plan["sheetName"], header=None, dtype=object)
    header_rows = plan["headerRows"] or [max(1, plan["dataStartRow"] - 1)]
    mappings = validated_column_mappings(
        raw,
        header_rows,
        dict(plan["columnMappings"]),
        full_service_beta,
        intake_mode,
        plan["dataStartRow"],
    )
    inferred_json = infer_json_mappings(raw, header_rows, plan["dataStartRow"])
    for key, mapping in inferred_json.items():
        mappings.setdefault(key, mapping)
    inferred = infer_column_mappings(raw, header_rows, full_service_beta, intake_mode, plan["dataStartRow"])
    for key, mapping in inferred.items():
        existing = mappings.get(key)
        if (
            key == "database_details_total_allocated_storage_gb"
            and existing
            and "total allocated" in normalize(mapping.get("sourceHeader"))
            and "total allocated" not in normalize(existing.get("sourceHeader"))
        ):
            mappings[key] = mapping
        else:
            mappings.setdefault(key, mapping)

    fields = canonical_fields_payload(full_service_beta, intake_mode)
    for field in fields:
        mapping = mappings.get(field["key"])
        if mapping:
            field["sourceColumn"] = mapping["sourceColumn"]
            field["sourceHeader"] = mapping.get("sourceHeader") or header_label(raw, header_rows, mapping["sourceColumn"] - 1)
            if mapping.get("jsonKey"):
                field["sourceJsonKey"] = mapping["jsonKey"]

    def build_rows(data_start_row, data_end_row):
        parsed_rows = []
        row_end = min(data_end_row or len(raw.index), len(raw.index))
        data_start_idx = max(0, data_start_row - 1)

        for raw_idx in range(data_start_idx, row_end):
            values = raw.iloc[raw_idx].tolist()
            if not any(clean_text(value) for value in values):
                continue

            row = {"__id": f"row-{raw_idx + 1}", "__sourceRow": raw_idx + 1, "__approved": True}
            for field in fields:
                mapping = mappings.get(field["key"])
                value = ""
                if mapping:
                    col_idx = mapping["sourceColumn"] - 1
                    if 0 <= col_idx < len(values):
                        value = values[col_idx]
                        if mapping.get("jsonKey") or mapping.get("jsonPath"):
                            value = value_from_json_cell(value, mapping.get("jsonKey") or mapping.get("jsonPath"))
                row[field["key"]] = normalize_inventory_value(field["key"], value)

            if plan["serverGrain"] in {"server", "vm", "host", "asset", "inventory row"}:
                has_resource_shape = clean_text(row.get("application_name")) or to_number(
                    row.get("application_details_number_of_cpu_cores_per_server")
                ) or to_number(row.get("application_details_memory_per_server_gb"))
                if not row.get("application_details_number_of_servers") and has_resource_shape:
                    row["application_details_number_of_servers"] = 1

            if should_keep_inventory_row(row):
                parsed_rows.append(row)
        return parsed_rows, row_end

    data_start_row = plan["dataStartRow"]
    rows, row_end = build_rows(data_start_row, plan.get("dataEndRow"))
    fallback_start_row = max(header_rows) + 1 if header_rows else 2
    if not rows and data_start_row != fallback_start_row:
        data_start_row = fallback_start_row
        rows, row_end = build_rows(data_start_row, None)

    if not rows:
        raise ValueError("The OpenAI workbook plan did not produce inventory rows.")

    return {
        "fileName": Path(path).name,
        "sheetName": plan["sheetName"],
        "sheets": excel_file.sheet_names,
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY, full_service_beta),
        "rateCards": all_shape_payloads(full_service_beta),
        "fullServiceCatalog": price_catalog_payload(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY, full_service_beta),
        "metadata": {
            "headerRows": header_rows,
            "dataStartRow": data_start_row,
            "dataEndRow": row_end,
            "rowCount": len(rows),
            "columnCount": len(fields),
            "parser": "llm-assisted",
            "intakeMode": intake_mode,
            "fullServiceBeta": bool(full_service_beta),
            "confidence": plan.get("confidence", 0),
            "serverGrain": plan.get("serverGrain", "unknown"),
            "extractionNotes": plan.get("notes", []),
        },
    }


CLOUD_PROVIDER_SIGNATURES = {
    "aws": [
        "lineitem",
        "line item",
        "productcode",
        "usageaccountid",
        "unblendedcost",
        "netunblendedcost",
        "aws",
        "amazon",
        "cur",
    ],
    "azure": [
        "metercategory",
        "metersubcategory",
        "metername",
        "costinbillingcurrency",
        "resourcelocation",
        "subscriptionid",
        "azure",
        "microsoft",
    ],
    "gcp": [
        "service description",
        "sku description",
        "usage amount",
        "usage unit",
        "project id",
        "location region",
        "billing account",
        "gcp",
        "google",
    ],
}

CLOUD_COLUMN_ALIASES = {
    "source_account": {
        "aws": ["lineitem usageaccountid", "line item usage account id", "bill payeraccountid", "usage account id"],
        "azure": ["subscriptionid", "subscription id", "subscriptionname", "subscription name"],
        "gcp": ["project id", "project name", "project number", "billing account id"],
        "common": ["account id", "account name", "project id", "subscription id", "billing account"],
    },
    "source_service": {
        "aws": ["product productname", "product product name", "lineitem productcode", "productcode", "service"],
        "azure": ["metercategory", "meter category", "consumedservice", "consumed service", "service name"],
        "gcp": ["service description", "service id", "service"],
        "common": ["service", "service name", "product name", "meter category"],
    },
    "source_product": {
        "aws": [
            "lineitem usagetype",
            "line item usage type",
            "lineitem lineitemdescription",
            "line item description",
            "product servicename",
            "operation",
        ],
        "azure": ["metername", "meter name", "metersubcategory", "meter subcategory", "productname", "product name"],
        "gcp": ["sku description", "sku id", "sku"],
        "common": ["sku", "meter", "meter name", "usage type", "description", "line item description"],
    },
    "source_region": {
        "aws": ["product region", "region", "lineitem availabilityzone", "availability zone"],
        "azure": ["resourcelocation", "resource location", "location"],
        "gcp": ["location region", "location location", "region"],
        "common": ["region", "resource location", "location", "availability zone"],
    },
    "usage_quantity": {
        "aws": ["lineitem usageamount", "line item usage amount", "usageamount", "usage amount"],
        "azure": ["quantity", "consumedquantity", "consumed quantity"],
        "gcp": ["usage amount", "usage amount in pricing units", "usage pricing unit quantity"],
        "common": ["usage amount", "usage quantity", "quantity", "qty", "consumed quantity"],
    },
    "usage_unit": {
        "aws": ["pricing unit", "pricing/unit", "usage unit", "unit"],
        "azure": ["unitofmeasure", "unit of measure", "unit"],
        "gcp": ["usage unit", "usage pricing unit"],
        "common": ["unit", "usage unit", "unit of measure", "pricing unit"],
    },
    "resource_ocpus": {
        "aws": ["vcpu", "vcpus", "cpu", "cpus", "core count"],
        "azure": ["vcpu", "vcpus", "cpu", "cpus", "core count"],
        "gcp": ["vcpu", "vcpus", "cpu", "cpus", "core count"],
        "common": ["ocpu", "ocpus", "vcpu", "vcpus", "cpu", "cpus", "cores", "core count"],
    },
    "resource_memory_gb": {
        "aws": ["memory", "memory gb", "ram", "ram gb"],
        "azure": ["memory", "memory gb", "ram", "ram gb"],
        "gcp": ["memory", "memory gb", "ram", "ram gb"],
        "common": ["memory", "memory gb", "ram", "ram gb", "mem gb", "gb ram"],
    },
    "source_monthly_cost": {
        "aws": ["lineitem netunblendedcost", "lineitem unblendedcost", "net unblended cost", "unblended cost"],
        "azure": ["costinbillingcurrency", "cost in billing currency", "pretaxcost", "pretax cost", "cost"],
        "gcp": ["cost", "net cost"],
        "common": ["cost", "source cost", "amount", "charge"],
    },
    "source_currency": {
        "aws": ["pricing currency", "currency"],
        "azure": ["billingcurrencycode", "billing currency code", "currency"],
        "gcp": ["currency"],
        "common": ["currency", "billing currency"],
    },
    "source_period": {
        "aws": ["lineitem usagestartdate", "usage start date", "bill billingperiodstartdate", "billing period"],
        "azure": ["date", "usagedate", "usage date"],
        "gcp": ["usage start time", "invoice month", "export time"],
        "common": ["date", "month", "billing period", "usage start date"],
    },
    "source_tags": {
        "aws": ["resource tags", "resource tag", "user tag", "tag"],
        "azure": ["tags", "additionalinfo", "additional info"],
        "gcp": ["labels", "system labels"],
        "common": ["tags", "labels"],
    },
}


def read_bill_table(path, sheet_name=None):
    suffix = Path(path).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        separator = "\t" if suffix == ".tsv" else None
        return pd.read_csv(path, header=None, dtype=object, sep=separator, engine="python")
    return pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)


def cloud_header_score(values):
    text = normalize(" ".join(clean_text(value) for value in values if clean_text(value)))
    if not text:
        return 0
    score = 0
    terms = {
        "service": 3,
        "sku": 3,
        "meter": 3,
        "usage": 4,
        "quantity": 3,
        "cost": 4,
        "currency": 2,
        "lineitem": 4,
        "subscription": 3,
        "project": 3,
        "region": 2,
    }
    for term, weight in terms.items():
        if term in text:
            score += weight
    return score


def detect_cloud_header_row(raw):
    sample_rows = min(25, len(raw.index))
    best_score = 0
    best_idx = 0
    for row_idx in range(sample_rows):
        values = raw.iloc[row_idx].tolist()
        score = cloud_header_score(values)
        if score > best_score:
            best_score = score
            best_idx = row_idx
    return best_idx


def unique_headers(values):
    headers = []
    seen = {}
    for col_idx, value in enumerate(values):
        label = clean_text(value) or f"Column {col_idx + 1}"
        count = seen.get(label, 0) + 1
        seen[label] = count
        headers.append(label if count == 1 else f"{label} {count}")
    return headers


def detect_cloud_provider(headers, sample_rows=None, provider_hint=PROVIDER_AUTO):
    provider_names = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}
    hint = normalize_provider_hint(provider_hint)
    if hint != PROVIDER_AUTO:
        return provider_names[hint], 1.0

    parts = [*headers]
    for row in (sample_rows or [])[:12]:
        parts.extend(clean_text(value) for value in row if clean_text(value))
    text = normalize(" ".join(parts))

    scores = {}
    for provider, terms in CLOUD_PROVIDER_SIGNATURES.items():
        scores[provider] = sum(1 for term in terms if normalize(term) in text)
    provider = max(scores, key=scores.get)
    score = scores.get(provider, 0)
    if score <= 0:
        return "Unknown", 0.0
    confidence = min(0.98, 0.34 + (score * 0.11))
    return provider_names[provider], round(confidence, 2)


def header_alias_score(header, aliases):
    header_norm = normalize(header)
    if not header_norm:
        return 0
    best = 0
    for alias in aliases:
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if header_norm == alias_norm:
            best = max(best, 120 + len(alias_norm))
        elif header_norm.endswith(alias_norm):
            best = max(best, 88 + len(alias_norm))
        elif alias_norm in header_norm:
            best = max(best, 64 + len(alias_norm))
        elif header_norm in alias_norm and len(header_norm) >= 4:
            best = max(best, 42 + len(header_norm))
    return best


def infer_cloud_bill_mappings(headers, detected_provider):
    provider = normalize_provider_hint(detected_provider)
    if provider == PROVIDER_AUTO and normalize(detected_provider) == "unknown":
        provider = "common"
    mappings = {}
    for field in CLOUD_BILL_FIELDS:
        aliases_by_provider = CLOUD_COLUMN_ALIASES.get(field["key"], {})
        aliases = [*aliases_by_provider.get(provider, []), *aliases_by_provider.get("common", []), *field["aliases"]]
        best_idx = None
        best_score = 0
        for idx, header in enumerate(headers):
            score = header_alias_score(header, aliases)
            if score > best_score:
                best_idx = idx
                best_score = score
        minimum_score = 64 if field["key"] in {"resource_ocpus", "resource_memory_gb"} else 48
        if best_idx is not None and best_score >= minimum_score:
            mappings[field["key"]] = {
                "canonicalKey": field["key"],
                "sourceColumn": best_idx + 1,
                "sourceHeader": headers[best_idx],
                "confidence": min(0.98, best_score / 150),
            }
    return mappings


def cloud_bill_value(key, value):
    if key in {"usage_quantity", "source_monthly_cost", "mapping_confidence"}:
        return compact_number(to_number(value, 0)) if clean_text(value) else ""
    if key == "resource_ocpus":
        return compact_number(to_number(value, 0)) if clean_text(value) else ""
    if key == "resource_memory_gb":
        return compact_number(to_gb(value)) if clean_text(value) else ""
    return clean_cell(value)


def value_at(values, index):
    return values[index] if 0 <= index < len(values) else ""


def text_at(values, index):
    return clean_text(value_at(values, index))


def numeric_text_only(value):
    text = clean_text(value)
    return bool(text and re.fullmatch(r"[\-$€£¥0-9,.\s%()]+", text))


def oci_mapping_text(value):
    text = clean_text(value)
    if not text:
        return ""
    normalized = normalize(text)
    if normalized in {"service", "services", "sku", "skus", "oci cost", "hrs", "hours", "instances", "bandwidth"}:
        return ""
    if "no direct mapping" in normalized:
        return ""
    if numeric_text_only(text):
        return ""
    return text


def embedded_azure_region(text):
    value = clean_text(text)
    if not value:
        return ""
    region_terms = [
        "US Central",
        "US East 2",
        "US East",
        "US North Central",
        "US South Central",
        "US West 3",
        "US West 2",
        "US West",
        "Canada Central",
        "Canada East",
        "Brazil South",
        "North Europe",
        "West Europe",
        "UK South",
        "UK West",
        "East Asia",
        "Southeast Asia",
        "Australia East",
        "Australia Southeast",
        "Central India",
        "South India",
        "West India",
        "Japan East",
        "Japan West",
        "Korea Central",
        "Korea South",
        "France Central",
        "Germany West Central",
        "Norway East",
        "Sweden Central",
        "Switzerland North",
        "UAE North",
    ]
    value_norm = normalize(value)
    for region in sorted(region_terms, key=len, reverse=True):
        if normalize(region) in value_norm:
            return region
    match = re.search(r"(?:-|,)\s*((?:US|Canada|Brazil|North|West|East|South|Central|Southeast|Australia|Japan|Korea|France|Germany|Norway|Sweden|Switzerland|UAE|UK|India)[A-Za-z ]*(?:\s\d)?)\b", value)
    return clean_text(match.group(1)) if match else ""


def azure_mapping_header_indexes(values):
    indexes = {}
    for idx, value in enumerate(values):
        normalized = normalize(value)
        if not normalized:
            continue
        if normalized in {"quantity", "qty"}:
            indexes["quantity"] = idx
        elif "unit" in normalized and "measure" in normalized:
            indexes["unit"] = idx
        elif normalized in {"vcpu", "vcpus", "cpu", "cpus"}:
            indexes["source_vcpu"] = idx
        elif normalized in {"ram", "memory", "memory gb", "ram gb"}:
            if idx >= 13:
                indexes["oci_ram"] = idx
            else:
                indexes["source_ram"] = idx
        elif normalized in {"ocpu or ecpu", "ocpu", "ecpu", "ocpus"}:
            indexes["oci_ocpu"] = idx
        elif normalized == "service":
            indexes["oci_service"] = idx
        elif normalized in {"skus", "sku"}:
            indexes["oci_sku"] = idx
        elif normalized == "oci cost":
            indexes["oci_cost"] = idx
        elif "cost" in normalized or clean_text(value).startswith("$"):
            indexes.setdefault("source_cost", idx)
    return indexes


def looks_like_azure_service_mapping_sheet(raw):
    preview = normalize(
        " ".join(
            clean_text(raw.iat[row_idx, col_idx])
            for row_idx in range(min(20, len(raw.index)))
            for col_idx in range(min(24, len(raw.columns)))
            if clean_text(raw.iat[row_idx, col_idx])
        )
    )
    return bool(
        "azure" in preview
        and "oci equivalent" in preview
        and "unit of measure" in preview
        and "skus" in preview
    )


def apply_cloud_field_source(fields, key, source_column, source_header):
    for field in fields:
        if field.get("key") == key:
            field["sourceColumn"] = source_column
            field["sourceHeader"] = source_header
            return


def parse_azure_service_mapping_table(path, sheet_name, raw, provider_hint=PROVIDER_AUTO, sheet_names=None):
    if normalize_provider_hint(provider_hint) not in {PROVIDER_AUTO, "azure"}:
        return None
    if "service mapping" not in normalize(sheet_name) and not looks_like_azure_service_mapping_sheet(raw):
        return None
    if not looks_like_azure_service_mapping_sheet(raw):
        return None

    fields = canonical_fields_payload(True, INTAKE_MODE_CLOUD_BILL)
    source_columns = {
        "source_service": (2, "Azure service group"),
        "source_product": (2, "Azure SKU / meter"),
        "usage_quantity": (3, "Quantity"),
        "usage_unit": (4, "Unit of Measure"),
        "resource_ocpus": (19, "OCI OCPU or ECPU"),
        "resource_memory_gb": (20, "OCI RAM"),
        "oci_service_category": (15, "OCI Service"),
        "oci_product": (16, "OCI SKUs"),
    }
    for key, (source_column, source_header) in source_columns.items():
        apply_cloud_field_source(fields, key, source_column, source_header)

    rows = []
    rate_card = build_rate_card(DEFAULT_SHAPE_KEY, True)
    current_service = ""
    current_target = ""
    current_header = {}
    first_header_row = None

    for raw_idx in range(len(raw.index)):
        values = raw.iloc[raw_idx].tolist()
        source_text = text_at(values, 1)
        quantity_text = text_at(values, 2)
        unit_text = text_at(values, 3)
        row_header = azure_mapping_header_indexes(values)
        is_section_header = bool(
            source_text
            and (
                normalize(quantity_text) in {"quantity", "qty"}
                or normalize(text_at(values, 14)) == "service"
                or normalize(text_at(values, 15)) in {"skus", "sku"}
            )
        )
        if is_section_header:
            current_service = source_text
            current_target = oci_mapping_text(text_at(values, 13))
            current_header = row_header
            first_header_row = first_header_row or raw_idx + 1
            continue

        if not source_text or normalize(source_text) in {"azure", "oci equivalent"}:
            continue
        if normalize(quantity_text) in {"quantity", "qty"} or normalize(unit_text) == "unit of measure":
            continue
        if not any(clean_text(value) for value in values):
            continue

        quantity = cloud_bill_value("usage_quantity", value_at(values, current_header.get("quantity", 2)))
        source_product = clean_cell(source_text)
        if not source_product and not quantity:
            continue

        source_cost = ""
        if "source_cost" in current_header:
            source_cost = cloud_bill_value("source_monthly_cost", value_at(values, current_header["source_cost"]))

        left_vcpu = to_number(value_at(values, current_header.get("source_vcpu", -1)), 0) if "source_vcpu" in current_header else 0
        left_ram = to_number(value_at(values, current_header.get("source_ram", -1)), 0) if "source_ram" in current_header else 0
        target_ocpus = to_number(value_at(values, current_header.get("oci_ocpu", -1)), 0) if "oci_ocpu" in current_header else 0
        target_ram = to_number(value_at(values, current_header.get("oci_ram", -1)), 0) if "oci_ram" in current_header else 0
        if not target_ram and "source_ram" in current_header:
            target_ram = left_ram
        if not target_ocpus and left_vcpu:
            target_ocpus = left_vcpu / 2

        row_target = oci_mapping_text(text_at(values, current_header.get("oci_service", 14))) or current_target
        row_sku = oci_mapping_text(text_at(values, current_header.get("oci_sku", 15)))
        no_direct_mapping = "no direct mapping" in normalize(text_at(values, 13)) or "no direct mapping" in normalize(current_target)

        row = {
            "__id": f"azure-map-row-{raw_idx + 1}",
            "__sourceRow": raw_idx + 1,
            "__approved": True,
            "source_provider": "Azure",
            "source_account": "",
            "source_service": current_service or source_product.split(" - ")[0],
            "source_product": source_product,
            "source_region": embedded_azure_region(source_product),
            "usage_quantity": quantity,
            "usage_unit": cloud_bill_value("usage_unit", value_at(values, current_header.get("unit", 3))),
            "resource_ocpus": compact_number(target_ocpus) if target_ocpus else "",
            "resource_memory_gb": compact_number(target_ram) if target_ram else "",
            "source_monthly_cost": source_cost,
            "source_currency": "USD",
            "source_period": "",
            "source_tags": f"Workbook sheet: {sheet_name}; source row {raw_idx + 1}",
            "oci_service_category": "" if no_direct_mapping else row_target,
            "oci_product": "" if no_direct_mapping else row_sku,
            "mapping_confidence": "",
        }
        seed_cloud_bill_mapping(row, fields, rate_card)
        if cloud_row_has_signal(row):
            rows.append(row)

    if not rows:
        return None

    mapped_count = sum(1 for row in rows if row_mapping_is_confident(row))
    return {
        "fileName": Path(path).name,
        "sheetName": sheet_name,
        "sheets": sheet_names or [sheet_name],
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY, True),
        "rateCards": all_shape_payloads(True),
        "fullServiceCatalog": price_catalog_payload(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY, True),
        "metadata": {
            "intakeMode": INTAKE_MODE_CLOUD_BILL,
            "providerHint": normalize_provider_hint(provider_hint),
            "detectedProvider": "Azure",
            "providerConfidence": 1,
            "parser": "azure-service-mapping-workbook",
            "sourceCurrency": "USD",
            "mappedCount": mapped_count,
            "unmappedCount": len(rows) - mapped_count,
            "headerRows": [first_header_row] if first_header_row else [],
            "dataStartRow": (first_header_row + 1) if first_header_row else 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
            "extractionNotes": [
                "Detected side-by-side Azure-to-OCI service mapping workbook.",
                "Azure source rows were read from the left side and OCI target service/SKU/resource values from the right side.",
            ],
        },
    }


def _load_cloud_shape_map():
    """Load the AWS/Azure/GCP -> OCI instance sizing reference (extracted from the mapping workbook)."""
    path = Path(__file__).resolve().parent / "data" / "cloud_shape_map.json"
    index = {}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return index
    for entry in payload.get("shapes", []):
        key = entry.get("key") or re.sub(r"[^a-z0-9]", "", str(entry.get("instance", "")).lower())
        if key:
            index.setdefault(key, entry)
    return index


# Exact per-instance sizing from the provided cloud mapping doc (authoritative over heuristics).
CLOUD_SHAPE_MAP = _load_cloud_shape_map()
# Longest keys first so e.g. "e2standard16" wins over a shorter accidental substring.
CLOUD_SHAPE_KEYS_BY_LEN = sorted(CLOUD_SHAPE_MAP.keys(), key=len, reverse=True)


def lookup_cloud_shape(context):
    """Return the mapping-doc record whose instance type appears in the bill context, else None."""
    collapsed = re.sub(r"[^a-z0-9]", "", str(context).lower())
    if not collapsed:
        return None
    for key in CLOUD_SHAPE_KEYS_BY_LEN:
        if len(key) >= 4 and key in collapsed:
            return CLOUD_SHAPE_MAP[key]
    return None


def _load_oci_shapes():
    path = Path(__file__).resolve().parent / "data" / "oci_shapes.json"
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"vendorTiers": {}, "allShapes": []}


OCI_SHAPES = _load_oci_shapes()
OCI_VENDOR_TIERS = OCI_SHAPES.get("vendorTiers", {})


def _load_oci_gpu_shapes():
    path = Path(__file__).resolve().parent / "data" / "oci_gpu_shapes.json"
    index = {}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return index
    for s in payload.get("shapes", []):
        index[s["shape"]] = s
    return index


OCI_GPU_SHAPES = _load_oci_gpu_shapes()
GPU_HOURS_PER_MONTH = 730


def gpu_pricing_for_context(context):
    """If a cloud-bill row maps to a GPU instance, return its OCI GPU shape pricing, else None."""
    rec = lookup_cloud_shape(context)
    if not rec or not rec.get("isGpu"):
        return None
    shape_name = rec.get("ociShape")
    cat = OCI_GPU_SHAPES.get(shape_name)
    if not cat:
        return None
    return {
        "shape": shape_name,
        "gpuModel": cat.get("gpuModel"),
        "gpuCount": cat.get("gpuCount"),
        "pricePerGpuHour": cat.get("pricePerGpuHour"),
        "mappable": rec.get("mappable", True),
        "flag": rec.get("mapFlag", ""),
    }

# Map each app flex shape to its OCI shape name, per-VM max OCPU/memory, and CPU vendor.
SHAPE_KEY_TO_OCI = {
    "e6-standard-ax": ("VM.Standard.E6.Ax.Flex", 94, 712, "amd"),
    "e5-standard": ("VM.Standard.E5.Flex", 94, 1049, "amd"),
    "e4-standard": ("VM.Standard.E4.Flex", 64, 1024, "amd"),
    "x9-standard": ("VM.Standard3.Flex", 32, 512, "intel"),
    "x12-standard-ax": ("VM.Standard4.Ax.Flex", 39, 360, "intel"),
}


def oci_size_check(shape_key, ocpus, memory_gb):
    """Classify a single VM's size against the selected OCI shape.

    Returns dict: status = ok | baremetal | impossible, with the fitting shape and a message.
    'baremetal' means it overflows the selected flex shape but fits an OCI bare-metal shape;
    'impossible' means it exceeds every OCI shape for that CPU vendor.
    """
    info = SHAPE_KEY_TO_OCI.get(shape_key)
    if not info or (ocpus <= 0 and memory_gb <= 0):
        return {"status": "ok"}
    flex_shape, max_ocpu, max_mem, vendor = info
    if ocpus <= max_ocpu and memory_gb <= max_mem:
        return {"status": "ok", "shape": flex_shape}
    # Overflows the selected flex shape — try the vendor's bare-metal tier.
    for tier in OCI_VENDOR_TIERS.get(vendor, []):
        if tier.get("tier") == "flex":
            continue
        if ocpus <= tier["maxOcpu"] and memory_gb <= tier["maxMem"]:
            return {
                "status": "baremetal",
                "shape": tier["shape"],
                "message": f"{ocpus:g} OCPU / {memory_gb:g} GB exceeds {flex_shape}; fits bare metal {tier['shape']}.",
            }
    biggest = (OCI_VENDOR_TIERS.get(vendor) or [{}])[-1]
    return {
        "status": "impossible",
        "shape": None,
        "message": (
            f"{ocpus:g} OCPU / {memory_gb:g} GB exceeds the largest OCI {vendor} shape "
            f"({biggest.get('shape')}: {biggest.get('maxOcpu')} OCPU / {biggest.get('maxMem')} GB)."
        ),
    }


AWS_INSTANCE_SIZE_SHAPES = {
    "nano": (2, 0.5),
    "micro": (2, 1),
    "small": (2, 2),
    "medium": (2, 4),
    "large": (2, 8),
    "xlarge": (4, 16),
    "2xlarge": (8, 32),
    "3xlarge": (12, 48),
    "4xlarge": (16, 64),
    "6xlarge": (24, 96),
    "8xlarge": (32, 128),
    "9xlarge": (36, 144),
    "10xlarge": (40, 160),
    "12xlarge": (48, 192),
    "16xlarge": (64, 256),
    "18xlarge": (72, 288),
    "24xlarge": (96, 384),
    "32xlarge": (128, 512),
}

GCP_MEMORY_RATIO_BY_CLASS = {
    "standard": 4,
    "highmem": 8,
    "highcpu": 0.9,
}

AZURE_MEMORY_RATIO_BY_FAMILY = {
    "b": 4,
    "d": 4,
    "e": 8,
    "f": 2,
}


def bill_usage_capacity_factor(quantity, unit_context):
    quantity_value = to_number(quantity, 0)
    if quantity_value <= 0:
        return 1.0
    has_instance_shape = bool(
        re.search(
            r"\b(?:[a-z]\d[a-z0-9]*|[a-z]{1,4}\d[a-z0-9]*)\.(?:nano|micro|small|medium|large|xlarge|[0-9]+xlarge)\b",
            unit_context,
        )
    )
    if re.search(r"\binstance ?(?:hours?|used|usage)\b|\bbox ?usage\b|\brunning ?hours?\b|\bvm ?hours?\b", unit_context):
        return quantity_value / HOURS_PER_MONTH
    if re.search(r"\binstance\b", unit_context) and re.search(r"\bhrs?\b|\bhours?\b", unit_context):
        return quantity_value / HOURS_PER_MONTH
    if has_instance_shape and re.search(r"\bhrs?\b|\bhours?\b", unit_context):
        return quantity_value / HOURS_PER_MONTH
    return quantity_value


def meter_capacity_quantity(quantity, unit_context, is_vcpu=False):
    quantity_value = to_number(quantity, 0)
    if quantity_value <= 0:
        return 0.0
    if re.search(r"\b(?:ocpu|vcpu|cpu|core|gb|gib)? ?hours?\b|gbhr|gibhr", unit_context) and quantity_value > HOURS_PER_MONTH:
        quantity_value = quantity_value / HOURS_PER_MONTH
    return quantity_value / 2 if is_vcpu else quantity_value


def infer_instance_shape_resources(context, usage_quantity="", usage_unit=""):
    unit_context = normalize(f"{usage_unit} {context}")
    capacity_factor = bill_usage_capacity_factor(usage_quantity, unit_context)

    # Authoritative: exact instance match from the cloud mapping reference doc.
    mapped = lookup_cloud_shape(context)
    if mapped:
        ocpus = to_number(mapped.get("ocpus"), 0)
        if not ocpus:
            ocpus = to_number(mapped.get("vcpu"), 0) / 2
        memory_gb = to_number(mapped.get("ramGb"), 0) or to_number(mapped.get("memoryGb"), 0)
        if ocpus or memory_gb:
            return ocpus * capacity_factor, memory_gb * capacity_factor

    aws_match = re.search(
        r"\b(?:[a-z]\d[a-z0-9]*|[a-z]{1,4}\d[a-z0-9]*)\.(nano|micro|small|medium|large|xlarge|[0-9]+xlarge)\b",
        context,
    )
    if aws_match:
        vcpus, memory_gb = AWS_INSTANCE_SIZE_SHAPES.get(aws_match.group(1), (0, 0))
        return (vcpus / 2) * capacity_factor, memory_gb * capacity_factor

    gcp_match = re.search(r"\b(?:e2|n1|n2|n2d|c2|c3|m1|m2|m3)-(standard|highmem|highcpu)-(\d+)\b", context)
    if gcp_match:
        machine_class = gcp_match.group(1)
        vcpus = to_number(gcp_match.group(2), 0)
        memory_gb = vcpus * GCP_MEMORY_RATIO_BY_CLASS.get(machine_class, 4)
        return (vcpus / 2) * capacity_factor, memory_gb * capacity_factor

    azure_match = re.search(r"\bstandard[_ -]([a-z]+)(\d+)[a-z0-9]*", context)
    if azure_match:
        family = azure_match.group(1)[:1]
        vcpus = to_number(azure_match.group(2), 0)
        memory_gb = vcpus * AZURE_MEMORY_RATIO_BY_FAMILY.get(family, 4)
        return (vcpus / 2) * capacity_factor, memory_gb * capacity_factor

    return 0.0, 0.0


def enrich_cloud_bill_resource_fields(row):
    raw_context = " ".join(
        clean_text(row.get(key))
        for key in [
            "source_provider",
            "source_service",
            "source_product",
            "usage_unit",
            "source_tags",
            "oci_service_category",
            "oci_product",
        ]
    )
    context = normalize(raw_context)
    quantity = row.get("usage_quantity")
    unit_context = normalize(f"{row.get('usage_unit')} {raw_context}")
    usage_unit_only = normalize(row.get("usage_unit"))
    if re.fullmatch(r"(mb|mib|gb|gib|tb|tib)", usage_unit_only):
        return

    if not to_number(row.get("resource_ocpus"), 0):
        if context_has_any(context, ["ocpu", "ocpu per hour", "ocpu hour"]):
            inferred = meter_capacity_quantity(quantity, unit_context)
            if inferred:
                row["resource_ocpus"] = compact_number(inferred)
        elif context_has_any(context, ["vcpu", "v cpu", "cpu hour", "cpu per hour", "core hour", "core per hour"]):
            inferred = meter_capacity_quantity(quantity, unit_context, is_vcpu=True)
            if inferred:
                row["resource_ocpus"] = compact_number(inferred)

    if not to_number(row.get("resource_memory_gb"), 0) and context_has_any(
        context,
        ["memory gb", "memory per hour", "gb per hour", "gb hour memory", "ram gb", "ram per hour"],
    ):
        inferred = meter_capacity_quantity(quantity, unit_context)
        if inferred:
            row["resource_memory_gb"] = compact_number(inferred)

    inferred_ocpus, inferred_memory_gb = infer_instance_shape_resources(
        clean_text(raw_context).lower(),
        quantity,
        row.get("usage_unit"),
    )
    if inferred_ocpus and not to_number(row.get("resource_ocpus"), 0):
        row["resource_ocpus"] = compact_number(inferred_ocpus)
    if inferred_memory_gb and not to_number(row.get("resource_memory_gb"), 0):
        row["resource_memory_gb"] = compact_number(inferred_memory_gb)


def detect_tag_columns(headers):
    tag_columns = []
    for idx, header in enumerate(headers):
        text = normalize(header)
        if "tag" in text or "label" in text:
            tag_columns.append((idx, header))
    return tag_columns


def summarize_source_tags(values, tag_columns, existing=""):
    parts = []
    if clean_text(existing):
        parts.append(clean_text(existing))
    for col_idx, header in tag_columns:
        if col_idx >= len(values):
            continue
        value = clean_text(values[col_idx])
        if not value:
            continue
        label = clean_text(header)
        parts.append(f"{label}={value}")
    return "; ".join(dict.fromkeys(parts))


def cloud_row_has_signal(row):
    return bool(
        clean_text(row.get("source_service"))
        or clean_text(row.get("source_product"))
        or clean_text(row.get("source_monthly_cost"))
        or clean_text(row.get("usage_quantity"))
        or clean_text(row.get("resource_ocpus"))
        or clean_text(row.get("resource_memory_gb"))
    )


def row_mapping_is_confident(row):
    return bool(clean_text(row.get("oci_product")) and "needs review" not in normalize(row.get("mapping_confidence")))


def row_maps_to_storage_meter(row):
    target = normalize(
        " ".join(
            [
                clean_text(row.get("oci_service_category")),
                clean_text(row.get("oci_product")),
                clean_text(row.get("source_service")),
                clean_text(row.get("source_product")),
                clean_text(row.get("usage_unit")),
            ]
        )
    )
    storage_terms = [
        "storage",
        "block volume",
        "volume storage",
        "object storage",
        "archive storage",
        "file storage",
        "managed disk",
        "persistent disk",
        "cold hdd",
        "snapshot",
        "gb month",
        "gb mo",
        "bytehrs",
    ]
    return context_has_any(target, storage_terms) and not context_has_any(target, ["memory", "ram"])


def clear_resource_fields_for_storage(row):
    if not row_maps_to_storage_meter(row):
        return
    row["resource_ocpus"] = ""
    row["resource_memory_gb"] = ""


def seed_cloud_bill_mapping(row, fields, rate_card):
    item, confidence = classify_full_service_item(row, fields)
    if item:
        row["oci_service_category"] = row.get("oci_service_category") or item.get("category", "")
        row["oci_product"] = row.get("oci_product") or item.get("description", "")
        if not clean_text(row.get("mapping_confidence")):
            row["mapping_confidence"] = f"{round(confidence * 100)}%"
        clear_resource_fields_for_storage(row)
        return

    target = infer_oci_service_target(row, fields)
    if target:
        row["oci_service_category"] = row.get("oci_service_category") or target["category"]
        row["oci_product"] = row.get("oci_product") or target["product"]
        row["mapping_confidence"] = row.get("mapping_confidence") or confidence_label(target["confidence"], target.get("reviewRequired", True))
        clear_resource_fields_for_storage(row)
        return

    row["mapping_confidence"] = row.get("mapping_confidence") or "Needs review"


def catalog_items_for_keys(keys):
    requested = set(keys or [])
    return [
        {
            "key": item["key"],
            "sku": item["sku"],
            "description": item["description"],
            "unit": item["unit"],
            "category": item["category"],
            "rate": item["rate"],
        }
        for item in FULL_SERVICE_CATALOG_ITEMS
        if not requested or item["key"] in requested
    ]


def provider_mapping_context(provider):
    provider_norm = normalize(provider)
    if provider_norm in {"aws", "amazon", "amazon web services"}:
        provider_terms = {"aws", "amazon"}
    elif provider_norm in {"azure", "microsoft azure", "microsoft"}:
        provider_terms = {"azure", "microsoft"}
    elif provider_norm in {"gcp", "google", "google cloud", "google cloud platform"}:
        provider_terms = {"gcp", "google"}
    else:
        provider_terms = set()

    context = []
    for mapping in OCI_SOURCE_SERVICE_MAPPINGS:
        source_text = normalize(" ".join(mapping["sourceServices"]))
        if not provider_terms or any(term in source_text for term in provider_terms):
            context.append({**mapping, "localCatalogCandidates": catalog_items_for_keys(mapping.get("catalogKeys"))})
    return context


def cloud_bill_pattern_key(row):
    parts = [
        normalize(row.get("source_provider")),
        normalize(row.get("source_service")),
        normalize(row.get("source_product")),
        normalize(row.get("usage_unit")),
    ]
    return "|".join(parts)


def compact_cloud_bill_patterns(rows, max_patterns=140):
    grouped = {}
    for row_index, row in enumerate(rows, start=1):
        key = cloud_bill_pattern_key(row)
        if not key.strip("|"):
            continue
        pattern = grouped.setdefault(
            key,
            {
                "patternId": f"pattern-{len(grouped) + 1}",
                "rowIds": [],
                "sampleRows": [],
                "provider": clean_text(row.get("source_provider")),
                "sourceService": clean_text(row.get("source_service")),
                "sourceProduct": clean_text(row.get("source_product")),
                "usageUnit": clean_text(row.get("usage_unit")),
                "sourceRegions": [],
                "sourceAccounts": [],
                "totalUsageQuantity": 0.0,
                "totalSourceMonthlyCost": 0.0,
            },
        )
        pattern["rowIds"].append(row.get("__id"))
        if len(pattern["sampleRows"]) < 3:
            pattern["sampleRows"].append(
                {
                    "rowId": row.get("__id"),
                    "sourceRow": row.get("__sourceRow"),
                    "usageQuantity": clean_cell(row.get("usage_quantity")),
                    "sourceMonthlyCost": clean_cell(row.get("source_monthly_cost")),
                    "sourceTags": clean_text(row.get("source_tags"))[:260],
                }
            )
        if clean_text(row.get("source_region")) and clean_text(row.get("source_region")) not in pattern["sourceRegions"]:
            pattern["sourceRegions"].append(clean_text(row.get("source_region")))
        if clean_text(row.get("source_account")) and clean_text(row.get("source_account")) not in pattern["sourceAccounts"]:
            pattern["sourceAccounts"].append(clean_text(row.get("source_account")))
        pattern["totalUsageQuantity"] += to_number(row.get("usage_quantity"), 0)
        pattern["totalSourceMonthlyCost"] += to_number(row.get("source_monthly_cost"), 0)

    patterns = sorted(
        grouped.values(),
        key=lambda item: (item["totalSourceMonthlyCost"], len(item["rowIds"]), item["totalUsageQuantity"]),
        reverse=True,
    )
    compacted = []
    pattern_rows = {}
    for pattern in patterns[:max_patterns]:
        pattern["rowCount"] = len(pattern["rowIds"])
        pattern["totalUsageQuantity"] = round(pattern["totalUsageQuantity"], 4)
        pattern["totalSourceMonthlyCost"] = money(pattern["totalSourceMonthlyCost"])
        pattern["sourceRegions"] = pattern["sourceRegions"][:6]
        pattern["sourceAccounts"] = pattern["sourceAccounts"][:6]
        pattern_rows[pattern["patternId"]] = pattern["rowIds"]
        compacted.append({key: value for key, value in pattern.items() if key != "rowIds"})
    return compacted, pattern_rows, len(patterns) > len(compacted)


def sanitized_bill_patterns(patterns):
    safe_patterns = []
    for pattern in patterns:
        safe_patterns.append(
            {
                "patternId": pattern["patternId"],
                "provider": pattern.get("provider"),
                "sourceService": pattern.get("sourceService"),
                "sourceProduct": pattern.get("sourceProduct"),
                "usageUnit": pattern.get("usageUnit"),
                "rowCount": pattern.get("rowCount"),
            }
        )
    return safe_patterns


def confidence_label(confidence, review_required=False):
    if isinstance(confidence, (int, float)):
        percent = max(0, min(100, round(float(confidence) * 100 if confidence <= 1 else float(confidence))))
        return "Needs review" if review_required and percent < 60 else f"{percent}%"
    text = clean_text(confidence)
    if not text:
        return "Needs review" if review_required else ""
    if review_required and "review" not in normalize(text):
        return f"{text} - Needs review"
    return text


def parse_quantity_multiplier(multiplier):
    if multiplier in {None, ""}:
        return None
    if isinstance(multiplier, (int, float)):
        return float(multiplier)
    text = clean_text(multiplier).lower()
    try:
        return float(text)
    except ValueError:
        pass
    compact = text.replace(" ", "")
    if compact in {"1/730", "1÷730"}:
        return 1 / HOURS_PER_MONTH
    if "1024" in compact and "730" in compact and compact.startswith("1/"):
        return 1 / (1024**3) / HOURS_PER_MONTH
    if compact in {"1/1024", "1÷1024"}:
        return 1 / 1024
    return None


def apply_quantity_multiplier(row, multiplier, target_unit):
    if multiplier in {None, ""}:
        if clean_text(target_unit):
            row["usage_unit"] = clean_text(target_unit)
        return
    factor = parse_quantity_multiplier(multiplier)
    if factor is None:
        if clean_text(target_unit):
            row["usage_unit"] = clean_text(target_unit)
        return
    quantity = to_number(row.get("usage_quantity"), 0)
    if quantity > 0:
        row["usage_quantity"] = compact_number(quantity * factor)
    if clean_text(target_unit):
        row["usage_unit"] = clean_text(target_unit)


def append_mapping_rationale(row, rationale):
    text = clean_text(rationale)
    if not text:
        return
    existing = clean_text(row.get("source_tags"))
    note = f"OCI mapping: {text[:260]}"
    if note in existing:
        return
    row["source_tags"] = "; ".join(part for part in [existing, note] if part)


def apply_cloud_bill_llm_mapping(parsed, llm_payload, pattern_rows):
    if not isinstance(llm_payload, dict):
        return 0, []
    rows_by_id = {row.get("__id"): row for row in parsed.get("rows", [])}
    applied = 0
    warnings_list = [clean_text(item) for item in llm_payload.get("warnings", []) if clean_text(item)]

    for mapping in llm_payload.get("mappings", []):
        if not isinstance(mapping, dict):
            continue
        row_ids = []
        pattern_id = clean_text(mapping.get("patternId"))
        if pattern_id:
            row_ids.extend(pattern_rows.get(pattern_id, []))
        row_id = clean_text(mapping.get("rowId"))
        if row_id:
            row_ids.append(row_id)
        row_ids = list(dict.fromkeys(row_id for row_id in row_ids if row_id in rows_by_id))
        if not row_ids:
            warnings_list.append(f"Skipped OCI mapping for unknown pattern or row: {pattern_id or row_id}.")
            continue

        category = clean_text(mapping.get("ociServiceCategory") or mapping.get("oci_service_category"))
        product = clean_text(mapping.get("ociProduct") or mapping.get("oci_product"))
        target_unit = clean_text(mapping.get("targetUsageUnit") or mapping.get("usageUnit") or mapping.get("usage_unit"))
        multiplier = mapping.get("quantityMultiplier")
        confidence = confidence_label(mapping.get("confidence"), bool(mapping.get("reviewRequired")))
        rationale = clean_text(mapping.get("rationale") or mapping.get("reasoning"))

        for row_id in row_ids:
            row = rows_by_id[row_id]
            if category:
                row["oci_service_category"] = category
            if product:
                row["oci_product"] = product
            if confidence:
                row["mapping_confidence"] = confidence
            elif mapping.get("reviewRequired"):
                row["mapping_confidence"] = "Needs review"
            apply_quantity_multiplier(row, multiplier, target_unit)
            append_mapping_rationale(row, rationale)
            clear_resource_fields_for_storage(row)
            applied += 1

    return applied, warnings_list


def call_llm_cloud_bill_mapping(parsed):
    rows = parsed.get("rows", [])
    if not rows:
        return parsed
    metadata = parsed.get("metadata", {})
    default_max_patterns = 30 if metadata.get("parser") == "cloud-bill-pdf" else 140
    max_patterns = int(os.environ.get("OPENAI_BILL_MAX_PATTERNS", default_max_patterns))
    patterns, pattern_rows, truncated = compact_cloud_bill_patterns(rows, max_patterns=max_patterns)
    if not patterns:
        return parsed

    provider = metadata.get("detectedProvider") or metadata.get("providerHint") or "Unknown"
    include_private_context = clean_text(os.environ.get("OPENAI_BILL_INCLUDE_PRIVATE_CONTEXT")).lower() in {"1", "true", "yes", "on"}
    system = (
        "You are an Oracle Cloud Infrastructure cloud-bill mapper. Return compact JSON only. "
        "Your primary job is to recognize source-cloud or document lines that imply compute/core usage, RAM/memory, and storage capacity or requests, then map those rows to OCI services and meters. "
        "Think through each source bill-line pattern using source provider, service, SKU/meter name, and usage unit. "
        "Map the source line to the closest OCI service and OCI price-list meter using the provided Oracle service mapping guide and metering rules. "
        "Use localCatalogCandidates when there is a trustworthy exact meter. If the local catalog does not include the needed OCI meter, still identify the OCI service/product but set reviewRequired true. "
        "Never use source-cloud cost as the OCI rate. Preserve separate meters; do not merge compute, memory, storage, request, and network rows. "
        "For vCPU/core-hour source usage mapped to OCI compute, use quantityMultiplier 0.5 and targetUsageUnit 'OCPU-hour'. "
        "For TB-month storage, use multiplier 1024 and targetUsageUnit 'GB-month'. For GB-hour storage, use multiplier 1/730 and targetUsageUnit 'GB-month'. "
        "For byte-hours object storage, use multiplier 1/(1024^3*730) and targetUsageUnit 'GB-month'. "
        "For noisy PDF invoices, map only the supplied high-impact patterns and omit anything you are not confident about. "
        "Return this exact shape: {summary:string, mappings:[{patternId:string, ociServiceCategory:string, ociProduct:string, "
        "targetUsageUnit:string, quantityMultiplier:number|null, confidence:number, reviewRequired:boolean, rationale:string}], warnings:[string]}."
    )
    payload = {
        "workflowContract": LLM_WORKFLOW_CONTRACT,
        "officialReferences": OCI_OFFICIAL_REFERENCES,
        "meteringGuidance": OCI_METERING_GUIDANCE,
        "sourceServiceMappings": provider_mapping_context(provider),
        "localOciPriceCatalog": price_catalog_payload(),
        "billMetadata": {
            "detectedProvider": metadata.get("detectedProvider"),
            "providerConfidence": metadata.get("providerConfidence"),
            "patternCount": len(patterns),
            "patternsTruncated": truncated,
            "privateContextIncluded": include_private_context,
        },
        "billLinePatterns": patterns if include_private_context else sanitized_bill_patterns(patterns),
    }
    llm_payload, warning = call_openai_json(
        system,
        payload,
        max_output_tokens=2200,
        timeout=90,
        model_env="OPENAI_BILL_MODEL",
        reasoning_effort_env="OPENAI_BILL_REASONING_EFFORT",
        default_reasoning_effort="medium",
    )
    metadata["llmBillMappingAttempted"] = True
    metadata["llmBillPatternCount"] = len(patterns)
    metadata["llmBillPatternsTruncated"] = truncated
    if warning:
        mapped_count = sum(1 for row in parsed.get("rows", []) if row_mapping_is_confident(row))
        metadata["mappedCount"] = mapped_count
        metadata["unmappedCount"] = max(0, len(parsed.get("rows", [])) - mapped_count)
        metadata["llmBillMappingWarning"] = warning
        metadata.setdefault("extractionNotes", []).append(
            "Used deterministic OCI bill mapping because OpenAI API calls are disconnected."
            if warning == OPENAI_DISABLED_MESSAGE
            else "Used deterministic OCI bill mapping because the OpenAI bill-mapping pass did not complete."
        )
        if mapped_count == 0:
            parsed["llmWarning"] = (
                "OpenAI API calls are temporarily disabled; used deterministic bill mapping."
                if warning == OPENAI_DISABLED_MESSAGE
                else f"Cloud bill OpenAI mapping did not complete; used deterministic bill mapping. Detail: {warning}"
            )
        return parsed

    applied, warnings_list = apply_cloud_bill_llm_mapping(parsed, llm_payload, pattern_rows)
    remapped_count = sum(1 for row in parsed.get("rows", []) if row_mapping_is_confident(row))
    metadata["llmBillMappedRows"] = applied
    metadata["mappedCount"] = remapped_count
    metadata["unmappedCount"] = max(0, len(parsed.get("rows", [])) - remapped_count)
    if clean_text(llm_payload.get("summary")):
        metadata.setdefault("extractionNotes", []).append(clean_text(llm_payload.get("summary")))
    if warnings_list:
        metadata.setdefault("extractionNotes", []).extend(warnings_list[:4])
    return parsed


PDF_SERVICE_KEYWORDS = [
    "amazon simple storage service",
    "simple storage service",
    "elastic block store",
    "ebs",
    "ec2",
    "elastic compute",
    "rds",
    "glacier",
    "efs",
    "azure storage",
    "blob storage",
    "managed disk",
    "virtual machines",
    "azure files",
    "gcp",
    "google cloud",
    "cloud storage",
    "compute engine",
    "persistent disk",
    "filestore",
    "bigquery",
    "object storage",
    "block storage",
    "file storage",
    "archive",
    "requests",
    "cloudtrail",
    "cloudwatch",
    "config",
    "data transfer",
    "elastic load balancing",
    "key management service",
    "simple email service",
    "simple notification service",
    "simple queue service",
    "simpledb",
    "virtual private cloud",
    "support business",
]


def extract_pdf_text(path):
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if clean_text(text):
            pages.append({"page": index + 1, "text": text})
    if not pages:
        raise ValueError("No selectable text was found in the PDF. Scanned image PDFs need OCR before upload.")
    return pages


def pdf_lines(path):
    lines = []
    for page in extract_pdf_text(path):
        raw_lines = re.split(r"[\r\n]+", page["text"])
        if len(raw_lines) <= 1:
            raw_lines = re.split(r"(?<=[.])\s+(?=[A-Z0-9$])", page["text"])
        for raw_line in raw_lines:
            line = clean_text(raw_line)
            if line:
                lines.append({"page": page["page"], "text": line})
    return lines


def pdf_money_amount(line):
    text = clean_text(line)
    matches = []
    for pattern in [
        r"(?:\$|USD\s+|US\$\s*)(-?\d[\d,]*(?:\.\d{2})?)",
        r"(-?\d[\d,]*(?:\.\d{2})?)\s*(?:USD|US dollars?)\b",
    ]:
        matches.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    if not matches and context_has_any(normalize(text), PDF_SERVICE_KEYWORDS):
        end_match = re.search(r"(-?\d[\d,]*\.\d{2})\s*$", text)
        if end_match:
            matches.append(end_match.group(1))
    if not matches:
        return ""
    return compact_number(to_number(matches[-1], 0))


def pdf_usage(line):
    patterns = [
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(GB[-\s]?(?:mo|month)|GiB[-\s]?(?:mo|month)|TB[-\s]?(?:mo|month))\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(ByteHrs?|Byte[-\s]?hours?|Bytes?[-\s]?hours?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*((?:vCPU|OCPU|CPU|core)[-\s]?hours?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(GB[-\s]?hours?|GiB[-\s]?hours?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(TB|TiB|GB|GiB|MB|MiB)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(requests?|API requests?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(events?|messages?|IOs?|operations?|metrics?|keys?|counts?|LCU[-\s]?hrs?|LoadBalancer[-\s]?hours?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(hours?|hrs?)\b",
        r"(-?\d[\d,]*(?:\.\d+)?)(ConfigurationItemRecorded)\b",
    ]
    matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, line, flags=re.IGNORECASE):
            matches.append((match.start(), match.group(1), match.group(2)))
    if matches:
        _, quantity, unit = sorted(matches, key=lambda item: item[0])[-1]
        return compact_number(to_number(quantity, 0)), clean_text(unit)
    return "", ""


def pdf_region(line):
    match = re.search(r"\b([a-z]{2,}-[a-z]+-\d+[a-z]?|[a-z]+[a-z ]+(?:us|eu|asia|uk|india|japan|korea|australia)\b)\b", line, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def pdf_service_context_for_line(line):
    text = normalize(line)
    rules = [
        (["cloudtrail"], "AWS CloudTrail"),
        (["cloudwatch", "putlogevents"], "Amazon CloudWatch"),
        (["aws config", "configurationitemrecorded"], "AWS Config"),
        (["data transfer", "bandwidth"], "AWS Data Transfer"),
        (["elastic load balancing", "loadbalancer", "load balancer"], "Elastic Load Balancing"),
        (["elastic compute cloud", "ec2", "linux unix", "windows amazon vpc", "instance hour"], "Amazon EC2"),
        (["elastic block store", "ebs"], "EBS"),
        (["aws iot", "registryandshadowoperations"], "AWS IoT"),
        (["key management service", "kms requests", "kms keys"], "AWS Key Management Service"),
        (["simple email service"], "Amazon Simple Email Service"),
        (["simple notification service", "sns api", "sns requests"], "Amazon Simple Notification Service"),
        (["simple queue service", "sqs requests", "sqs"], "Amazon Simple Queue Service"),
        (["simple storage service", "timedstorage bytehrs", "requests tier"], "Amazon Simple Storage Service"),
        (["simpledb"], "Amazon SimpleDB"),
        (["virtual private cloud", "createvpnconnection"], "Amazon Virtual Private Cloud"),
        (["support business", "aws support"], "AWS Support"),
        (["efs", "elastic file system"], "Amazon EFS"),
        (["rds", "relational database"], "Amazon RDS"),
    ]
    for terms, service in rules:
        if context_has_any(text, terms):
            return service
    return ""


def pdf_service_for_line(line):
    service = pdf_service_context_for_line(line)
    text = normalize(line)
    if service == "Amazon Simple Storage Service" or context_has_any(text, ["object storage", "cloud storage"]):
        return "Object Storage", "Object storage usage"
    if context_has_any(text, ["glacier", "archive", "coldline"]):
        return "Archive Storage", "Archive storage usage"
    if service == "EBS" or context_has_any(text, ["elastic block store", "managed disk", "persistent disk", "block storage"]):
        return "Block Storage", "Block storage usage"
    if service == "Amazon EFS" or context_has_any(text, ["azure files", "filestore", "file storage"]):
        return "File Storage", "File storage usage"
    if service == "Amazon EC2" or context_has_any(text, ["elastic compute", "virtual machines", "compute engine", "vcpu", "ocpu", "cpu hour"]):
        return "Compute", "Compute usage"
    if context_has_term(text, "bigquery"):
        return "Analytics", "BigQuery usage"
    return service, clean_text(line)[:180] if service else ""


def pdf_has_bill_signal(line):
    text = normalize(line)
    return context_has_any(text, PDF_SERVICE_KEYWORDS)


def pdf_boilerplate_or_region(line):
    text = normalize(line)
    if not text:
        return True
    if re.fullmatch(r"\$?\d[\d,]*(?:\.\d{2})?", clean_text(line)):
        return True
    boilerplate_terms = [
        "billing management console",
        "console aws amazon com",
        "linked account can t download reports",
        "contact your payer account",
        "billing statement",
        "date printed",
        "account number",
        "payer account id",
        "details",
        "aws service charges",
        "summary usd",
    ]
    if any(term in text for term in boilerplate_terms):
        return True
    region_terms = [
        "asia pacific",
        "canada central",
        "eu frankfurt",
        "eu ireland",
        "eu london",
        "eu paris",
        "south america sao paulo",
        "us east",
        "us west",
        "any",
    ]
    return any(text == term or text.startswith(f"{term} ") for term in region_terms)


def pdf_candidate_lines(lines):
    candidates = []
    current_service = ""
    consumed = set()
    for index, item in enumerate(lines):
        if index in consumed:
            continue
        line = item["text"]
        if pdf_boilerplate_or_region(line):
            continue

        explicit_service = pdf_service_context_for_line(line)
        if explicit_service:
            current_service = explicit_service

        usage_quantity, _ = pdf_usage(line)
        has_money = pdf_money_amount(line) != ""
        has_meter_text = " per " in f" {normalize(line)} " or usage_quantity != ""

        if explicit_service:
            if not has_money and not has_meter_text:
                continue
            combined = line
        elif current_service and (has_meter_text or has_money):
            combined = f"{current_service} {line}"
        else:
            continue

        if index + 1 < len(lines):
            next_line = lines[index + 1]["text"]
            next_explicit_service = pdf_service_context_for_line(next_line)
            next_usage, _ = pdf_usage(next_line)
            next_has_detail = (" per " in f" {normalize(next_line)} " or next_usage != "") and not next_explicit_service
            if next_has_detail and not pdf_boilerplate_or_region(next_line):
                combined = f"{combined} {next_line}"
                consumed.add(index + 1)
        if not pdf_has_bill_signal(combined) and not current_service:
            continue
        candidates.append({"page": item["page"], "line": index + 1, "text": clean_text(combined)})
    return candidates


def parse_pdf_cloud_bill(path, provider_hint=PROVIDER_AUTO):
    lines = pdf_lines(path)
    detected_provider, provider_confidence = detect_cloud_provider([], [[item["text"]] for item in lines], provider_hint)
    fields = canonical_fields_payload(True, INTAKE_MODE_CLOUD_BILL)
    rows = []
    rate_card = build_rate_card(DEFAULT_SHAPE_KEY, True)
    for index, item in enumerate(pdf_candidate_lines(lines)):
        service, product = pdf_service_for_line(item["text"])
        source_cost = pdf_money_amount(item["text"])
        usage_quantity, usage_unit = pdf_usage(item["text"])
        row = {"__id": f"pdf-line-{index + 1}", "__sourceRow": f"p{item['page']} l{item['line']}", "__approved": True}
        for field in fields:
            row[field["key"]] = ""
        row["source_provider"] = detected_provider if detected_provider != "Unknown" else ""
        row["source_service"] = service or "PDF bill line"
        row["source_product"] = product or item["text"][:180]
        row["source_region"] = pdf_region(item["text"])
        row["usage_quantity"] = usage_quantity
        row["usage_unit"] = usage_unit
        row["source_monthly_cost"] = source_cost
        row["source_currency"] = "USD" if "$" in item["text"] or "usd" in normalize(item["text"]) else ""
        row["source_tags"] = f"PDF page {item['page']}, line {item['line']}: {item['text'][:220]}"
        enrich_cloud_bill_resource_fields(row)
        seed_cloud_bill_mapping(row, fields, rate_card)
        if cloud_row_has_signal(row):
            rows.append(row)

    if not rows:
        amounts = [pdf_money_amount(item["text"]) for item in lines]
        amounts = [amount for amount in amounts if amount != ""]
        row = {"__id": "pdf-summary-1", "__sourceRow": "PDF summary", "__approved": True}
        for field in fields:
            row[field["key"]] = ""
        row["source_provider"] = detected_provider if detected_provider != "Unknown" else ""
        row["source_service"] = "PDF bill summary"
        row["source_product"] = "No line-item table was detected. Review this PDF summary before pricing."
        row["source_monthly_cost"] = amounts[-1] if amounts else ""
        row["source_currency"] = "USD"
        row["mapping_confidence"] = "Needs review"
        enrich_cloud_bill_resource_fields(row)
        rows.append(row)

    mapped_count = sum(1 for row in rows if row_mapping_is_confident(row))
    currency_values = [clean_text(row.get("source_currency")) for row in rows if clean_text(row.get("source_currency"))]
    source_currency = currency_values[0] if currency_values else "USD"
    parsed = {
        "fileName": Path(path).name,
        "sheetName": "PDF bill",
        "sheets": ["PDF bill"],
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY, True),
        "rateCards": all_shape_payloads(True),
        "fullServiceCatalog": price_catalog_payload(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY, True),
        "metadata": {
            "intakeMode": INTAKE_MODE_CLOUD_BILL,
            "providerHint": normalize_provider_hint(provider_hint),
            "detectedProvider": detected_provider,
            "providerConfidence": provider_confidence,
            "parser": "cloud-bill-pdf",
            "sourceCurrency": source_currency,
            "mappedCount": mapped_count,
            "unmappedCount": len(rows) - mapped_count,
            "headerRows": [],
            "dataStartRow": 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
        },
    }
    return call_llm_cloud_bill_mapping(parsed)


def parse_cloud_bill(path, provider_hint=PROVIDER_AUTO):
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf_cloud_bill(path, provider_hint)

    candidate_tables = []
    if suffix in {".csv", ".tsv"}:
        raw = read_bill_table(path)
        header_row = detect_cloud_header_row(raw)
        headers = unique_headers(raw.iloc[header_row].tolist())
        candidate_tables.append(("Cloud bill", raw, header_row, headers))
    else:
        excel_file = pd.ExcelFile(path)
        dedicated_parsed = None
        for sheet in excel_file.sheet_names:
            raw = read_bill_table(path, sheet)
            if dedicated_parsed is None:
                dedicated_parsed = parse_azure_service_mapping_table(path, sheet, raw, provider_hint, excel_file.sheet_names)
            header_row = detect_cloud_header_row(raw)
            headers = unique_headers(raw.iloc[header_row].tolist())
            candidate_tables.append((sheet, raw, header_row, headers))
        if dedicated_parsed:
            return call_llm_cloud_bill_mapping(dedicated_parsed)

    if not candidate_tables:
        raise ValueError("No bill rows were found.")

    sheet_name, raw, header_row, headers = max(candidate_tables, key=lambda item: cloud_header_score(item[3]))
    data_start_idx = header_row + 1
    sample_values = [raw.iloc[idx].tolist() for idx in range(data_start_idx, min(len(raw.index), data_start_idx + 12))]
    detected_provider, provider_confidence = detect_cloud_provider(headers, sample_values, provider_hint)
    mappings = infer_cloud_bill_mappings(headers, detected_provider)
    fields = canonical_fields_payload(True, INTAKE_MODE_CLOUD_BILL)
    for field in fields:
        mapping = mappings.get(field["key"])
        if mapping:
            field["sourceColumn"] = mapping["sourceColumn"]
            field["sourceHeader"] = mapping["sourceHeader"]

    tag_columns = detect_tag_columns(headers)
    rows = []
    rate_card = build_rate_card(DEFAULT_SHAPE_KEY, True)
    provider_label = detected_provider if detected_provider != "Unknown" else ""
    for raw_idx in range(data_start_idx, len(raw.index)):
        values = raw.iloc[raw_idx].tolist()
        if not any(clean_text(value) for value in values):
            continue
        row = {"__id": f"bill-row-{raw_idx + 1}", "__sourceRow": raw_idx + 1, "__approved": True}
        for field in fields:
            mapping = mappings.get(field["key"])
            value = ""
            if mapping:
                col_idx = mapping["sourceColumn"] - 1
                if 0 <= col_idx < len(values):
                    value = values[col_idx]
            row[field["key"]] = cloud_bill_value(field["key"], value)
        row["source_provider"] = row.get("source_provider") or provider_label
        row["source_currency"] = row.get("source_currency") or "USD"
        row["source_tags"] = summarize_source_tags(values, tag_columns, row.get("source_tags"))
        enrich_cloud_bill_resource_fields(row)
        seed_cloud_bill_mapping(row, fields, rate_card)
        if cloud_row_has_signal(row):
            rows.append(row)

    if not rows:
        raise ValueError("The cloud bill parser did not find usable bill line rows.")

    mapped_count = sum(1 for row in rows if row_mapping_is_confident(row))
    currency_values = [clean_text(row.get("source_currency")) for row in rows if clean_text(row.get("source_currency"))]
    source_currency = currency_values[0] if currency_values else "USD"
    parsed = {
        "fileName": Path(path).name,
        "sheetName": sheet_name,
        "sheets": [item[0] for item in candidate_tables],
        "fields": fields,
        "rows": rows,
        "rateCard": build_rate_card(DEFAULT_SHAPE_KEY, True),
        "rateCards": all_shape_payloads(True),
        "fullServiceCatalog": price_catalog_payload(),
        "selectedShape": shape_payload(DEFAULT_SHAPE_KEY, True),
        "metadata": {
            "intakeMode": INTAKE_MODE_CLOUD_BILL,
            "providerHint": normalize_provider_hint(provider_hint),
            "detectedProvider": detected_provider,
            "providerConfidence": provider_confidence,
            "parser": "cloud-bill-adapter",
            "sourceCurrency": source_currency,
            "mappedCount": mapped_count,
            "unmappedCount": len(rows) - mapped_count,
            "headerRows": [header_row + 1],
            "dataStartRow": data_start_idx + 1,
            "rowCount": len(rows),
            "columnCount": len(fields),
        },
    }
    return call_llm_cloud_bill_mapping(parsed)


def parse_workbook(path, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM, provider_hint=PROVIDER_AUTO):
    if intake_mode == INTAKE_MODE_CLOUD_BILL:
        return parse_cloud_bill(path, provider_hint)

    llm_warning = None
    try:
        plan, llm_warning = call_llm_workbook_plan(path, full_service_beta)
        if plan:
            return parse_workbook_from_plan(path, plan, full_service_beta, intake_mode)
    except Exception as exc:
        llm_warning = f"OpenAI workbook interpretation did not complete; used rule-based spreadsheet parsing. Detail: {exc}"

    parsed = parse_workbook_rule_based(path, full_service_beta)
    if llm_warning:
        parsed["llmWarning"] = llm_warning
    return parsed


def find_key(fields, contains, section=None):
    needles = [normalize(item) for item in contains]
    section_norm = normalize(section) if section else ""
    for field in fields:
        label_norm = normalize(field["label"])
        if section_norm and not label_norm.startswith(section_norm):
            continue
        if all(needle in label_norm for needle in needles):
            return field["key"]
    return None


def find_key_exact(fields, labels):
    targets = {normalize(label) for label in labels}
    for field in fields:
        label_norm = normalize(field.get("label"))
        source_norm = normalize(field.get("sourceHeader"))
        if label_norm in targets or source_norm in targets:
            return field["key"]
    return None


def value_for(row, key, default=0.0):
    return to_number(row.get(key), default) if key else default


def row_operating_system(row):
    """Scan all source values of a row for an OS hint (matches the BOM script)."""
    detected = ""
    for key, value in row.items():
        if isinstance(key, str) and key.startswith("__"):
            continue
        text = str(value).lower()
        if "windows" in text:
            return "windows"
        if "linux" in text:
            detected = "linux"
    return detected


def field_by_key(fields, key):
    return next((field for field in fields if field.get("key") == key), None)


def field_is_ocpu(fields, key):
    field = field_by_key(fields, key)
    return bool(field and "ocpu" in normalize(field.get("label")))


def field_text(fields, key):
    field = field_by_key(fields, key)
    if not field:
        return ""
    return normalize(" ".join(clean_text(field.get(item)) for item in ["label", "sourceHeader", "description"]))


def storage_field_is_row_total(fields, key):
    text = field_text(fields, key)
    if not key or not text:
        return False
    if any(term in text for term in ["per server", "per vm", "per host", "per instance", "per node"]):
        return False
    return any(term in text for term in ["total storage", "total allocated", "allocated storage", "storage total"])


def ocpus_for_review_value(fields, key, value):
    if not key or not value:
        return 0.0
    return value if field_is_ocpu(fields, key) else value / 2


def text_for(row, fields, contains, section=None):
    key = find_key(fields, contains, section)
    return clean_text(row.get(key, "")) if key else ""


def text_for_exact(row, fields, labels):
    key = find_key_exact(fields, labels)
    return clean_text(row.get(key, "")) if key else ""


def rate(sku, rate_card):
    for item in rate_card:
        if item["sku"] == sku:
            return item
    raise KeyError(sku)


def money(value):
    return round(float(value), 2)


def find_key_any(fields, groups, section=None):
    for contains in groups:
        key = find_key(fields, contains, section)
        if key:
            return key
    return None


def text_from_any(row, fields, canonical_key, groups):
    value = clean_text(row.get(canonical_key))
    if value:
        return value
    key = find_key_any(fields, groups)
    return clean_text(row.get(key, "")) if key else ""


def row_context(row, fields):
    parts = []
    for field in fields:
        key = field.get("key")
        value = clean_text(row.get(key))
        if not key or not value:
            continue
        parts.append(f"{field.get('label', key)} {value}")
    return normalize(" ".join(parts))


def detect_source_provider(provider, context):
    provider_text = clean_text(provider)
    if provider_text:
        return provider_text
    if re.search(r"\baws\b|amazon|cur|cost explorer|ec2|s3|ebs|efs|rds", context):
        return "AWS"
    if re.search(r"\bazure\b|microsoft|managed disk|blob|azure files|meter category", context):
        return "Azure"
    if re.search(r"\bgcp\b|google cloud|cloud storage|persistent disk|filestore|bigquery", context):
        return "GCP"
    if re.search(r"on prem|on premise|on premises|vmware|vcenter|esxi|hyper v|san|nas|nfs|smb", context):
        return "On-prem"
    return ""


def context_has_term(context, term):
    term_norm = normalize(term)
    if not term_norm:
        return False
    if len(term_norm) <= 3 or re.fullmatch(r"[a-z]+\d+|\d+[a-z]+", term_norm):
        return bool(re.search(rf"(^|\s){re.escape(term_norm)}($|\s)", context))
    return term_norm in context


def context_has_any(context, terms):
    return any(context_has_term(context, term) for term in terms)


def infer_oci_service_target(row, fields):
    context = row_context(row, fields)
    target = normalize(
        " ".join(
            [
                clean_text(row.get("source_service")),
                clean_text(row.get("source_product")),
                clean_text(row.get("source_tags")),
            ]
        )
    )
    haystack = f"{target} {context}"

    rules = [
        {
            "terms": ["cloudtrail", "freeeventsrecorded", "events recorded"],
            "category": "Security",
            "product": "OCI Audit / Logging",
            "confidence": 0.78,
            "reviewRequired": True,
        },
        {
            "terms": ["cloudwatch", "putlogevents", "metric month", "logs", "log data ingested"],
            "category": "Observability and Management",
            "product": "OCI Monitoring / Logging",
            "confidence": 0.82,
            "reviewRequired": True,
        },
        {
            "terms": ["aws config", "configurationitemrecorded", "configuration item recorded"],
            "category": "Observability and Management",
            "product": "OCI Cloud Guard / Resource Manager",
            "confidence": 0.7,
            "reviewRequired": True,
        },
        {
            "terms": ["data transfer", "bandwidth", "out bytes", "in bytes", "gb data processed"],
            "category": "Networking",
            "product": "OCI Networking data transfer",
            "confidence": 0.76,
            "reviewRequired": True,
        },
        {
            "terms": ["elastic load balancing", "loadbalancer", "load balancer", "lcu hrs", "lcu hour"],
            "category": "Networking",
            "product": "OCI Load Balancer",
            "confidence": 0.82,
            "reviewRequired": True,
        },
        {
            "terms": ["elastic compute cloud", "ec2", "instance hour", "instancehour", "boxusage", "linux unix", "windows amazon vpc"],
            "category": "Compute",
            "product": "OCI Virtual Machine Instances",
            "confidence": 0.78,
            "reviewRequired": True,
        },
        {
            "terms": ["key management service", "kms requests", "kms keys", "customer managed kms"],
            "category": "Security",
            "product": "OCI Vault",
            "confidence": 0.82,
            "reviewRequired": True,
        },
        {
            "terms": ["aws iot", "registryandshadowoperations", "device shadow", "device registry"],
            "category": "Integration",
            "product": "OCI application integration / IoT equivalent",
            "confidence": 0.62,
            "reviewRequired": True,
        },
        {
            "terms": ["simple email service", "sendemail", "sendrawemail"],
            "category": "Developer Services",
            "product": "OCI Email Delivery",
            "confidence": 0.86,
            "reviewRequired": True,
        },
        {
            "terms": ["simple notification service", "sns api", "sns requests"],
            "category": "Developer Services",
            "product": "OCI Notifications",
            "confidence": 0.86,
            "reviewRequired": True,
        },
        {
            "terms": ["simple queue service", "sqs requests", "sqs"],
            "category": "Developer Services",
            "product": "OCI Queue",
            "confidence": 0.86,
            "reviewRequired": True,
        },
        {
            "terms": ["simpledb"],
            "category": "Open Source Databases",
            "product": "Oracle NoSQL Database / Autonomous JSON Database",
            "confidence": 0.58,
            "reviewRequired": True,
        },
        {
            "terms": ["virtual private cloud", "createvpnconnection", "vpn connection"],
            "category": "Networking",
            "product": "OCI VPN Connect / Virtual Cloud Network",
            "confidence": 0.82,
            "reviewRequired": True,
        },
        {
            "terms": ["support business", "aws support"],
            "category": "Customer Success Services",
            "product": "Oracle Cloud support services",
            "confidence": 0.7,
            "reviewRequired": True,
        },
    ]
    for rule in rules:
        if context_has_any(haystack, rule["terms"]):
            return rule
    return None


def classify_full_service_item(row, fields):
    context = row_context(row, fields)
    target = normalize(
        " ".join(
            [
                clean_text(row.get("oci_product")),
                clean_text(row.get("oci_service_category")),
                clean_text(row.get("source_service")),
                clean_text(row.get("source_product")),
            ]
        )
    )
    haystack = f"{target} {context}"
    review_only_service_terms = [
        "cloudwatch",
        "cloudtrail",
        "aws config",
        "data transfer",
        "elastic load balancing",
        "instancehour",
        "key management service",
        "aws iot",
        "simple notification service",
        "simple queue service",
        "simple email service",
        "simpledb",
        "virtual private cloud",
        "support business",
    ]
    if context_has_any(haystack, review_only_service_terms):
        return None, 0.0

    for item in FULL_SERVICE_CATALOG_ITEMS:
        if item["sku"].lower() in haystack:
            return item, 0.96
        if normalize(item["description"]) and normalize(item["description"]) in haystack:
            return item, 0.92

    object_terms = ["object", "s3", "blob", "bucket", "gcs", "cloud storage", "simple storage service", "timedstorage", "bytehrs"]
    request_terms = ["request", "requests", "api", "put", "get", "list"]
    archive_terms = ["archive", "glacier", "deep archive", "coldline", "cold storage"]
    file_terms = ["efs", "azure files", "file share", "filestore", "nfs", "smb", "nas", "file storage"]
    block_terms = [
        "ebs",
        "managed disk",
        "persistent disk",
        "block",
        "volume",
        "san",
        "disk",
        "gp2",
        "gp3",
        "ssd",
        "magnetic provisioned storage",
        "cold hdd",
        "snapshot data stored",
        "provisioned storage",
        "optimized storage",
        "postgresql optimized storage",
        "gb month",
        "gb mo",
    ]
    compute_terms = ["ocpu", "vcpu", "cpu hour", "cpu-hour", "core hour", "core-hour", "compute unit"]
    memory_terms = ["memory gb hour", "memory gb-hour", "ram gb hour", "ram gb-hour", "gb hour memory", "gb-hour memory"]
    plain_data_unit = bool(re.fullmatch(r"(mb|mib|gb|gib|tb|tib)", normalize(row.get("usage_unit"))))

    if plain_data_unit and context_has_any(haystack, block_terms):
        return FULL_SERVICE_RATE_BY_KEY["block_volume_storage"], 0.86
    if plain_data_unit and context_has_any(haystack, object_terms):
        return FULL_SERVICE_RATE_BY_KEY["object_storage_standard"], 0.86
    if context_has_any(haystack, compute_terms):
        return FULL_SERVICE_RATE_BY_KEY["compute_ocpu_hours"], 0.9
    if context_has_any(haystack, memory_terms):
        return FULL_SERVICE_RATE_BY_KEY["memory_gb_hours"], 0.9
    if context_has_any(haystack, request_terms) and context_has_any(haystack, object_terms):
        return FULL_SERVICE_RATE_BY_KEY["object_storage_requests"], 0.88
    if context_has_any(haystack, archive_terms):
        return FULL_SERVICE_RATE_BY_KEY["archive_storage"], 0.9
    if context_has_any(haystack, file_terms):
        return FULL_SERVICE_RATE_BY_KEY["file_storage"], 0.88
    if context_has_any(haystack, block_terms):
        return FULL_SERVICE_RATE_BY_KEY["block_volume_storage"], 0.86
    if context_has_any(haystack, object_terms):
        return FULL_SERVICE_RATE_BY_KEY["object_storage_standard"], 0.86
    return None, 0.0


def request_quantity(quantity_text, unit_text, context):
    quantity = to_number(quantity_text, 0)
    if quantity <= 0:
        return 0.0
    unit_norm = normalize(f"{unit_text} {context}")
    if re.search(r"\bbillion\b|1 000 000 000|1000000000", unit_norm):
        return quantity * 1000000000
    if re.search(r"\bmillion\b|1 000 000|1000000|1m\b", unit_norm):
        return quantity * 1000000
    if re.search(r"\b10k\b|10 000|10000|ten thousand", unit_norm):
        return quantity * 10000
    if re.search(r"\bthousand\b|1 000|1000|1k\b", unit_norm):
        return quantity * 1000
    return quantity


def storage_gb_month_quantity(quantity_text, unit_text, context):
    quantity = to_number(quantity_text, 0)
    if quantity <= 0:
        return 0.0
    unit_context = normalize(f"{unit_text} {context}")
    if re.search(r"byte ?hrs|byte ?hours|byte hour|bytehrs", unit_context):
        return quantity / (1024**3) / HOURS_PER_MONTH
    if re.search(r"byte ?seconds|byte second|bytesec|byte sec", unit_context):
        return quantity / (1024**3) / (HOURS_PER_MONTH * 3600)
    if re.search(r"\btb ?hours?\b|tib ?hours?", unit_context):
        return (quantity * 1024) / HOURS_PER_MONTH
    if re.search(r"\bgb ?hours?\b|gib ?hours?", unit_context):
        return quantity / HOURS_PER_MONTH
    if re.search(r"\bmb ?hours?\b|mib ?hours?", unit_context):
        return (quantity / 1024) / HOURS_PER_MONTH
    return to_gb(f"{quantity_text} {unit_text}", 0)


def usage_quantity_is_hours(quantity_text, unit_text, context, row=None):
    quantity = to_number(quantity_text, 0)
    if quantity <= 0:
        return False
    unit_context = normalize(f"{unit_text} {context}")
    unit_only = normalize(unit_text)
    if re.search(r"\bhrs?\b|\bhours?\b", unit_context):
        return True
    if row and unit_only in {"", "1", "unit", "units"} and (
        to_number(row.get("resource_ocpus"), 0) or to_number(row.get("resource_memory_gb"), 0)
    ):
        return True
    return False


def cloud_usage_hours(row, fields):
    context = row_context(row, fields)
    quantity_text = text_from_any(row, fields, "usage_quantity", [["usage", "quantity"], ["usage", "amount"], ["quantity"], ["consumed"]])
    unit_text = text_from_any(row, fields, "usage_unit", [["usage", "unit"], ["unit"], ["unit", "measure"], ["pricing", "unit"]])
    return to_number(quantity_text, 0) if usage_quantity_is_hours(quantity_text, unit_text, context, row) else 0.0


def source_only_context(row):
    return normalize(
        " ".join(
            clean_text(row.get(key))
            for key in [
                "source_provider",
                "source_service",
                "source_product",
                "usage_unit",
                "source_tags",
            ]
        )
    )


def quantity_for_full_service_item(item, quantity_text, unit_text, context, row=None):
    if not clean_text(quantity_text):
        return 0.0
    unit_context = normalize(f"{unit_text} {context}")
    if item["unit"] == "OCPU-hour":
        resource_ocpus = to_number(row.get("resource_ocpus"), 0) if row else 0
        if resource_ocpus and usage_quantity_is_hours(quantity_text, unit_text, context, row):
            return to_number(quantity_text, 0) * resource_ocpus
        source_context = source_only_context(row) if row else context
        inferred_ocpus, _ = infer_instance_shape_resources(source_context or context, quantity_text, unit_text)
        if inferred_ocpus and re.search(r"\bhrs?\b|\bhours?\b|instance|box ?usage", unit_context):
            return inferred_ocpus * HOURS_PER_MONTH
        is_vcpu = not re.search(r"\bocpus?\b", unit_context) and bool(
            re.search(r"\bvcpus?\b|\bv cpu\b|\bvcores?\b|\bv core\b|\bcpus?\b|\bcores?\b", unit_context)
        )
        if re.search(r"\bhrs?\b|\bhours?\b", unit_context):
            quantity = to_number(quantity_text, 0)
            return quantity / 2 if is_vcpu else quantity
        return meter_capacity_quantity(quantity_text, unit_context, is_vcpu=is_vcpu)
    if item["unit"] == "GB-hour":
        resource_memory_gb = to_number(row.get("resource_memory_gb"), 0) if row else 0
        if resource_memory_gb and usage_quantity_is_hours(quantity_text, unit_text, context, row):
            return to_number(quantity_text, 0) * resource_memory_gb
        return meter_capacity_quantity(quantity_text, unit_context)
    if item["unit"] == "GB-month":
        return storage_gb_month_quantity(quantity_text, unit_text, context)
    if item["unit"] == "10,000 requests":
        return request_quantity(quantity_text, unit_text, context) / 10000
    return to_number(quantity_text, 0)


def full_service_signal(row, fields):
    context = row_context(row, fields)
    if any(clean_text(row.get(key)) for key in SOURCE_SERVICE_FIELD_KEYS):
        return True
    return bool(
        re.search(
            r"\baws\b|amazon|azure|gcp|google cloud|on prem|on premise|vmware|s3|ebs|efs|blob|managed disk|persistent disk|filestore|glacier|archive|san|nas|nfs|smb",
            context,
        )
    )


def full_service_line_items(row, fields, rate_card=None):
    if not full_service_signal(row, fields):
        return [], None, []

    context = row_context(row, fields)
    provider = detect_source_provider(
        text_from_any(row, fields, "source_provider", [["provider"], ["cloud"], ["vendor"]]),
        context,
    )
    service = text_from_any(
        row,
        fields,
        "source_service",
        [["service"], ["meter", "category"], ["product", "code"], ["resource", "type"]],
    )
    product = text_from_any(
        row,
        fields,
        "source_product",
        [["usage", "type"], ["meter", "name"], ["sku"], ["product", "name"], ["item", "description"]],
    )
    region = text_from_any(row, fields, "source_region", [["region"], ["location"], ["datacenter"], ["data", "center"]])
    quantity_text = text_from_any(row, fields, "usage_quantity", [["usage", "quantity"], ["usage", "amount"], ["quantity"], ["consumed"]])
    unit_text = text_from_any(row, fields, "usage_unit", [["usage", "unit"], ["unit"], ["unit", "measure"], ["pricing", "unit"]])
    source_cost = text_from_any(row, fields, "source_monthly_cost", [["monthly", "cost"], ["cost"], ["charge"], ["amount"]])
    source_account = text_from_any(row, fields, "source_account", [["account"], ["subscription"], ["project"]])
    source_currency = text_from_any(row, fields, "source_currency", [["currency"], ["billing", "currency"]]) or "USD"
    source_period = text_from_any(row, fields, "source_period", [["period"], ["date"], ["month"]])
    source_tags = text_from_any(row, fields, "source_tags", [["tags"], ["labels"]])

    item, confidence = classify_full_service_item(row, fields)
    if not item:
        note = "Full-service beta saw this row but could not match it to the local OCI price-list subset."
        return [], {
            "sourceProvider": provider,
            "sourceAccount": source_account,
            "sourceService": service,
            "sourceProduct": product,
            "sourceRegion": region,
            "sourceMonthlyCost": money(to_number(source_cost, 0)) if source_cost else 0,
            "sourceCurrency": source_currency,
            "sourcePeriod": source_period,
            "sourceTags": source_tags,
            "confidence": 0,
            "reviewRequired": True,
        }, [note]

    quantity = quantity_for_full_service_item(item, quantity_text, unit_text, context, row)
    if quantity <= 0:
        note = f"{item['description']} was inferred, but no usable usage quantity was present for OCI pricing."
        return [], {
            "sku": item["sku"],
            "ociProduct": item["description"],
            "sourceProvider": provider,
            "sourceAccount": source_account,
            "sourceService": service,
            "sourceProduct": product,
            "sourceRegion": region,
            "sourceMonthlyCost": money(to_number(source_cost, 0)) if source_cost else 0,
            "sourceCurrency": source_currency,
            "sourcePeriod": source_period,
            "sourceTags": source_tags,
            "confidence": round(confidence, 2),
            "reviewRequired": True,
        }, [note]

    priced_item = item
    if rate_card:
        priced_item = next((candidate for candidate in rate_card if candidate.get("sku") == item["sku"]), None)
        if not priced_item and item["unit"] in {"OCPU-hour", "GB-hour"}:
            priced_item = next((candidate for candidate in rate_card if candidate.get("unit") == item["unit"]), None)
        priced_item = priced_item or item
    monthly = money(quantity * priced_item["rate"])
    line_item = {
        "sku": priced_item["sku"],
        "description": priced_item["description"],
        "quantity": round(quantity, 4),
        "unit": item["unit"],
        "rate": priced_item["rate"],
        "monthly": monthly,
        "mapping": f"{provider or 'Source'} {service or product or 'usage'} maps to {item['description']}.",
    }
    mapping = {
        "sku": priced_item["sku"],
        "ociProduct": priced_item["description"],
        "sourceProvider": provider,
        "sourceAccount": source_account,
        "sourceService": service,
        "sourceProduct": product,
        "sourceRegion": region,
        "sourceMonthlyCost": money(to_number(source_cost, 0)) if source_cost else 0,
        "sourceCurrency": source_currency,
        "sourcePeriod": source_period,
        "sourceTags": source_tags,
        "quantity": round(quantity, 4),
        "unit": item["unit"],
        "confidence": round(confidence, 2),
        "reviewRequired": confidence < 0.9,
    }
    return [line_item], mapping, []


def calculate_pricing(fields, rows, shape_key=DEFAULT_SHAPE_KEY, full_service_beta=False, intake_mode=INTAKE_MODE_ON_PREM, bom_match=False, hide_gpu_pricing=False, hide_windows_pricing=False, rightsize=False):
    def _rightsize_mem(ocpu_value, mem_value):
        # Cap memory at the OCI target ratio of 8 GB/OCPU (never increase it). OCPUs unchanged.
        if not rightsize or not ocpu_value or not mem_value:
            return mem_value
        return min(mem_value, math.ceil(ocpu_value * RIGHTSIZE_MEM_PER_OCPU))
    cloud_bill_mode = intake_mode == INTAKE_MODE_CLOUD_BILL
    service_catalog_enabled = bool(full_service_beta or cloud_bill_mode)
    selected_shape = shape_payload(shape_key, service_catalog_enabled)
    rate_card = selected_shape["rateCard"]
    keys = {
        "app_servers": find_key(fields, ["number of servers"], "Application Details"),
        "app_cpu": find_key_any(
            fields,
            [["ocpus per server"], ["ocpu"], ["number of cpu cores per server"], ["vcpu"], ["cpu cores"], ["cores"]],
            "Application Details",
        )
        or find_key_any(fields, [["ocpus per server"], ["ocpu"], ["number of cpu cores per server"], ["vcpu"], ["cpu cores"], ["cores"]]),
        "app_memory": find_key_any(
            fields,
            [["memory per server"], ["memory"], ["ram"], ["memory gb"], ["ram gb"]],
            "Application Details",
        )
        or find_key_any(fields, [["memory per server"], ["memory"], ["ram"], ["memory gb"], ["ram gb"]]),
        "app_local_storage": find_key_any(
            fields,
            [["local storage"], ["total storage"], ["allocated storage"], ["storage gb"], ["disk gb"], ["disk size"], ["disk capacity"]],
            "Application Details",
        )
        or find_key_any(fields, [["local storage"], ["total storage"], ["allocated storage"], ["storage gb"], ["disk gb"], ["disk size"], ["disk capacity"]]),
        "app_shared_storage": find_key_any(fields, [["shared storage"], ["file storage"], ["nas"], ["nfs"], ["smb"]], "Application Details")
        or find_key_any(fields, [["shared storage"], ["file storage"], ["nas"], ["nfs"], ["smb"]]),
        "db_servers": find_key(fields, ["number of database servers"], "Database Details"),
        "db_cpu": find_key_any(
            fields,
            [["ocpus per server"], ["ocpu"], ["database cpu"], ["db cpu"], ["database cores"], ["database vcpu"], ["number of cpu cores per server"]],
            "Database Details",
        )
        or find_key_any(fields, [["database ocpu"], ["database cpu"], ["db cpu"], ["database cores"], ["database vcpu"]]),
        "db_memory": find_key_any(
            fields,
            [["memory per server"], ["database memory"], ["db memory"], ["database ram"], ["db ram"], ["memory"], ["ram"]],
            "Database Details",
        )
        or find_key_any(fields, [["database memory"], ["db memory"], ["database ram"], ["db ram"]]),
        "db_total_allocated": find_key(fields, ["total allocated storage"], "Database Details"),
        "db_total_storage": find_key(fields, ["total storage"], "Database Details"),
        "db_size": find_key(fields, ["database size"], "Database Details"),
    }

    priced_rows = []
    totals = {
        "ocpus": 0.0,
        "memoryGb": 0.0,
        "blockStorageGb": 0.0,
        "fileStorageGb": 0.0,
        "fullServiceMonthly": 0.0,
        "mappedServiceRows": 0,
        "unpricedServiceRows": 0,
        "oversizeRows": 0,
        "impossibleRows": 0,
        "sourceMonthlyCost": 0.0,
        "mappedSourceMonthlyCost": 0.0,
        "unmappedSourceMonthlyCost": 0.0,
        "monthly": 0.0,
        "annual": 0.0,
    }

    def append_compute_memory_items(target_items, ocpus_value, memory_gb_value, mapping_prefix, hours_value=HOURS_PER_MONTH):
        hours = hours_value if hours_value and hours_value > 0 else HOURS_PER_MONTH
        if ocpus_value:
            rc = rate(selected_shape.get("computeSku", "B97384"), rate_card)
            qty = ocpus_value * hours
            target_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(qty, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(qty * rc["rate"]),
                    "mapping": mapping_prefix,
                }
            )
        if memory_gb_value:
            rc = rate(selected_shape.get("memorySku", "B97385"), rate_card)
            qty = memory_gb_value * hours
            target_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(qty, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(qty * rc["rate"]),
                    "mapping": "Memory is billed as GB-hours.",
                }
            )

    for row_index, row in enumerate(rows, start=1):
        if row.get("__approved") is False:
            continue

        app_servers = 0.0 if cloud_bill_mode else value_for(row, keys["app_servers"])
        db_servers = 0.0 if cloud_bill_mode else value_for(row, keys["db_servers"])
        app_cpu = 0.0 if cloud_bill_mode else value_for(row, keys["app_cpu"])
        db_cpu = 0.0 if cloud_bill_mode else value_for(row, keys["db_cpu"])
        app_memory = 0.0 if cloud_bill_mode else value_for(row, keys["app_memory"])
        db_memory = 0.0 if cloud_bill_mode else value_for(row, keys["db_memory"])
        if not cloud_bill_mode and not keys["app_servers"] and (app_cpu or app_memory):
            app_servers = 1.0
        if not cloud_bill_mode and not keys["db_servers"] and (db_cpu or db_memory):
            db_servers = 1.0
        app_local_storage = 0.0 if cloud_bill_mode else value_for(row, keys["app_local_storage"])
        app_shared_storage = 0.0 if cloud_bill_mode else value_for(row, keys["app_shared_storage"])

        storage_key = keys["db_total_allocated"] or keys["db_total_storage"] or keys["db_size"]
        db_storage = 0.0 if cloud_bill_mode else value_for(row, storage_key)

        if cloud_bill_mode:
            app_ocpus = value_for(row, "resource_ocpus")
            db_ocpus = 0.0
            ocpus = app_ocpus
            memory_gb = value_for(row, "resource_memory_gb")
        elif bom_match:
            # BOM-script mode: CPU column is treated as OCPUs directly (no vCPU/2),
            # and CPU/RAM are floored so fractions are never priced (matches the script).
            app_cpu_units = math.floor(app_cpu) if app_cpu else 0.0
            db_cpu_units = math.floor(db_cpu) if db_cpu else 0.0
            app_mem_units = math.floor(app_memory) if app_memory else 0.0
            db_mem_units = math.floor(db_memory) if db_memory else 0.0
            app_ocpus = app_servers * app_cpu_units if app_servers and app_cpu_units else 0.0
            db_ocpus = db_servers * db_cpu_units if db_servers and db_cpu_units else 0.0
            ocpus = app_ocpus + db_ocpus
            memory_gb = (app_servers * app_mem_units) + (db_servers * db_mem_units)
        else:
            app_ocpus = app_servers * ocpus_for_review_value(fields, keys["app_cpu"], app_cpu) if app_servers and app_cpu else 0.0
            db_ocpus = db_servers * ocpus_for_review_value(fields, keys["db_cpu"], db_cpu) if db_servers and db_cpu else 0.0
            ocpus = app_ocpus + db_ocpus
            memory_gb = (app_servers * app_memory) + (db_servers * db_memory)

        # Rightsize and Cut Costs: cap memory at 8 GB/OCPU (OCPUs unchanged) when enabled.
        original_memory_gb = memory_gb
        memory_gb = _rightsize_mem(ocpus, memory_gb)

        local_storage_multiplier = 1.0 if storage_field_is_row_total(fields, keys["app_local_storage"]) else app_servers
        shared_storage_multiplier = 1.0 if storage_field_is_row_total(fields, keys["app_shared_storage"]) else app_servers
        block_storage_gb = (local_storage_multiplier * app_local_storage) + db_storage
        file_storage_gb = shared_storage_multiplier * app_shared_storage

        line_items = []
        if not cloud_bill_mode:
            append_compute_memory_items(
                line_items,
                ocpus,
                memory_gb,
                "Spreadsheet CPU values are assumed to be vCPUs, shown in review as OCPUs using 2 vCPUs = 1 OCPU, then multiplied by 730 monthly hours.",
            )
            # Windows OS license: OS recognition scans the row; Windows rows are licensed per OCPU-hour
            # (1 license per OCPU = 1 per 2 vCPUs). Skipped when Windows pricing is toggled off.
            if ocpus and not hide_windows_pricing and row_operating_system(row) == "windows":
                win_rc = rate(WINDOWS_LICENSE_SKU, rate_card)
                win_qty = ocpus * HOURS_PER_MONTH
                line_items.append(
                    {
                        "sku": win_rc["sku"],
                        "description": win_rc["description"],
                        "quantity": round(win_qty, 4),
                        "unit": win_rc["unit"],
                        "rate": win_rc["rate"],
                        "monthly": money(win_qty * win_rc["rate"]),
                        "mapping": "Row detected as Windows; Windows OS licensing applied at OCPU-hours x 730.",
                    }
                )
        if block_storage_gb:
            rc = rate("B91961", rate_card)
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(block_storage_gb, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(block_storage_gb * rc["rate"]),
                    "mapping": "Local VM storage and database allocated storage map to block volume GB-months.",
                }
            )
            # Block volume performance units: 10 units per GB of block storage (BOM script Balanced tier).
            perf_rc = rate("B91962", rate_card)
            perf_qty = BLOCK_PERFORMANCE_UNITS_PER_GB * block_storage_gb
            line_items.append(
                {
                    "sku": perf_rc["sku"],
                    "description": perf_rc["description"],
                    "quantity": round(perf_qty, 4),
                    "unit": perf_rc["unit"],
                    "rate": perf_rc["rate"],
                    "monthly": money(perf_qty * perf_rc["rate"]),
                    "mapping": "Block volume performance units = 10 x block storage GB (Balanced performance).",
                }
            )
        if file_storage_gb:
            rc = rate("B89057", rate_card)
            line_items.append(
                {
                    "sku": rc["sku"],
                    "description": rc["description"],
                    "quantity": round(file_storage_gb, 4),
                    "unit": rc["unit"],
                    "rate": rc["rate"],
                    "monthly": money(file_storage_gb * rc["rate"]),
                    "mapping": "Shared storage maps to file storage GB-months.",
                }
            )

        full_service_mapping = None
        full_service_notes = []
        if service_catalog_enabled:
            service_items, full_service_mapping, full_service_notes = full_service_line_items(row, fields, rate_card)
            line_items.extend(service_items)
            fallback_start = len(line_items)
            service_units = {item.get("unit") for item in service_items}
            allow_compute_memory_fallback = not service_items or bool(service_units & {"OCPU-hour", "GB-hour"})
            usage_hours = cloud_usage_hours(row, fields) if cloud_bill_mode else HOURS_PER_MONTH
            if cloud_bill_mode and allow_compute_memory_fallback and (ocpus or memory_gb):
                existing_units = {item.get("unit") for item in line_items}
                append_compute_memory_items(
                    line_items,
                    0 if "OCPU-hour" in existing_units else ocpus,
                    0 if "GB-hour" in existing_units else memory_gb,
                    "Cloud bill CPU/vCPU usage was normalized to OCPUs and priced using source usage hours when present.",
                    usage_hours,
                )
            fallback_items = line_items[fallback_start:]
            source_cost_value = full_service_mapping.get("sourceMonthlyCost", 0) if full_service_mapping else 0
            totals["sourceMonthlyCost"] += source_cost_value
            if service_items or fallback_items:
                totals["fullServiceMonthly"] += sum(item["monthly"] for item in [*service_items, *fallback_items])
                totals["mappedServiceRows"] += 1
                totals["mappedSourceMonthlyCost"] += source_cost_value
            elif full_service_mapping:
                totals["unpricedServiceRows"] += 1
                totals["unmappedSourceMonthlyCost"] += source_cost_value

        gpu_info = gpu_pricing_for_context(row_context(row, fields)) if cloud_bill_mode else None
        if gpu_info:
            # OCI GPU bare-metal pricing replaces flex OCPU/memory (the host is bundled in the GPU price).
            line_items = [li for li in line_items if li.get("unit") not in {"OCPU-hour", "GB-hour"}]
            price = gpu_info.get("pricePerGpuHour")
            count = gpu_info.get("gpuCount") or 0
            gpu_desc = f"GPU - {gpu_info.get('gpuModel')} ({gpu_info['shape']})"
            if price and count and not hide_gpu_pricing:
                qty = count * GPU_HOURS_PER_MONTH
                line_items.append({
                    "sku": gpu_info["shape"],
                    "description": gpu_desc,
                    "quantity": round(qty, 4),
                    "unit": "GPU-hour",
                    "rate": price,
                    "monthly": money(qty * price),
                    "mapping": f"Mapped to OCI GPU shape {gpu_info['shape']} ({count}x {gpu_info.get('gpuModel')}); priced per GPU-hour x 730.",
                    "isGpu": True,
                })
            elif hide_gpu_pricing:
                line_items.append({
                    "sku": gpu_info["shape"], "description": gpu_desc, "quantity": 0,
                    "unit": "GPU-hour", "rate": price or 0, "monthly": 0.0,
                    "mapping": "GPU pricing hidden by toggle.", "isGpu": True, "gpuHidden": True,
                })

        monthly = money(sum(item["monthly"] for item in line_items))
        annual = money(monthly * 12)
        source_row_label = clean_text(row.get("__sourceRow"))
        fallback_name = f"Workload {source_row_label}" if source_row_label.isdigit() else f"Workload {row_index}"
        name = (
            text_for(row, fields, ["application name"])
            or text_for_exact(row, fields, ["application", "app"])
            or text_for(row, fields, ["database name"])
            or clean_text(row.get("source_service"))
            or clean_text(row.get("source_product"))
            or fallback_name
        )
        environment = text_for(row, fields, ["environment"]) or clean_text(row.get("source_account")) or clean_text(row.get("source_region"))
        assumptions = [
            "Spreadsheet CPU values are assumed to be vCPUs and converted in review using 2 vCPUs = 1 OCPU.",
            "OCPU and memory prices are converted to monthly estimates using 730 hours.",
            "Local VM storage plus database allocated storage are treated as block volume storage.",
            "Application shared storage is treated as file storage.",
        ]
        if service_catalog_enabled:
            assumptions.append("Recognized AWS, Azure, GCP, and on-prem rows are mapped to a curated Oracle price-list subset.")
            assumptions.extend(full_service_notes)

        # Per-VM feasibility against the selected OCI shape (single VM, not the row aggregate).
        if cloud_bill_mode:
            per_vm_specs = [(value_for(row, "resource_ocpus"), value_for(row, "resource_memory_gb"))]
        elif bom_match:
            per_vm_specs = [
                (math.floor(app_cpu) if app_cpu else 0, math.floor(app_memory) if app_memory else 0),
                (math.floor(db_cpu) if db_cpu else 0, math.floor(db_memory) if db_memory else 0),
            ]
        else:
            per_vm_specs = [
                (ocpus_for_review_value(fields, keys["app_cpu"], app_cpu), app_memory),
                (ocpus_for_review_value(fields, keys["db_cpu"], db_cpu), db_memory),
            ]
        size_check = {"status": "ok"}
        _rank = {"ok": 0, "baremetal": 1, "impossible": 2}
        for vm_ocpu, vm_mem in per_vm_specs:
            vm_mem = _rightsize_mem(vm_ocpu, vm_mem)
            if (vm_ocpu or 0) <= 0 and (vm_mem or 0) <= 0:
                continue
            chk = oci_size_check(shape_key, float(vm_ocpu or 0), float(vm_mem or 0))
            if _rank[chk["status"]] > _rank[size_check["status"]]:
                size_check = chk
        if size_check["status"] == "impossible":
            totals["impossibleRows"] += 1
        elif size_check["status"] == "baremetal":
            totals["oversizeRows"] += 1

        # Source-cloud cost estimate (other-cloud comparison): Linux baseline + Windows license add-on.
        # Windows add-on mirrors the OCI rule (1 license per OCPU) and is gated by the Windows toggle.
        is_windows_row = row_operating_system(row) == "windows"
        windows_addon = money(ocpus * WINDOWS_LICENSE_RATE * HOURS_PER_MONTH) if (is_windows_row and not hide_windows_pricing and ocpus) else 0.0
        src_rec = lookup_cloud_shape(row_context(row, fields))
        source_cloud_estimate = None
        # GCP: keep sizing/mapping only, no estimated source-cloud pricing.
        if src_rec and src_rec.get("provider") != "gcp" and src_rec.get("approxSourceMonthly") is not None:
            base = src_rec["approxSourceMonthly"]
            source_cloud_estimate = {
                "provider": src_rec.get("provider"),
                "instance": src_rec.get("instance"),
                "osDetected": "windows" if is_windows_row else "linux",
                "linuxMonthly": base,
                "windowsAddOnMonthly": windows_addon,
                "totalMonthly": money(base + windows_addon),
                "priceSource": "real" if src_rec.get("sourcePriceReal") else "estimate",
            }

        priced = {
            "rowId": row["__id"],
            "sourceRow": row.get("__sourceRow"),
            "name": name,
            "environment": environment,
            "sizeCheck": size_check,
            "windowsLicenseMonthly": windows_addon,
            "sourceCloudEstimate": source_cloud_estimate,
            "rightsized": bool(rightsize and original_memory_gb and memory_gb != original_memory_gb),
            "originalMemoryGb": round(original_memory_gb, 4),
            "specs": {
                "applicationServers": app_servers,
                "databaseServers": db_servers,
                "vcpus": round(ocpus * 2, 4),
                "ocpus": round(ocpus, 4),
                "memoryGb": round(memory_gb, 4),
                "blockStorageGb": round(block_storage_gb, 4),
                "fileStorageGb": round(file_storage_gb, 4),
            },
            "fullServiceMapping": full_service_mapping,
            "lineItems": line_items,
            "monthly": monthly,
            "annual": annual,
            "assumptions": assumptions,
        }
        priced_rows.append(priced)

        for key in ["ocpus", "memoryGb", "blockStorageGb", "fileStorageGb"]:
            totals[key] += priced["specs"][key]
        totals["monthly"] += monthly
        totals["annual"] += annual

    for key in totals:
        if key in {"monthly", "annual", "fullServiceMonthly", "sourceMonthlyCost", "mappedSourceMonthlyCost", "unmappedSourceMonthlyCost"}:
            totals[key] = money(totals[key])
        elif key in {"mappedServiceRows", "unpricedServiceRows", "oversizeRows", "impossibleRows"}:
            totals[key] = int(totals[key])
        else:
            totals[key] = round(totals[key], 4)

    return {
        "engine": "local-rule-engine",
        "intakeMode": intake_mode,
        "fullServiceBeta": service_catalog_enabled,
        "cloudBillMode": cloud_bill_mode,
        "hoursPerMonth": HOURS_PER_MONTH,
        "selectedShape": selected_shape,
        "rateCard": rate_card,
        "rateCards": all_shape_payloads(service_catalog_enabled),
        "totals": totals,
        "rows": priced_rows,
        "fieldMap": keys,
        "priceCatalog": price_catalog_payload() if service_catalog_enabled else [],
    }


def extract_response_text(payload):
    if "output_text" in payload:
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    return "\n".join(chunks)


def parse_jsonish(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def compact_llm_summary(pricing):
    sample_rows = []
    for row in pricing["rows"][:12]:
        sample_rows.append(
            {
                "rowId": row["rowId"],
                "name": row["name"],
                "environment": row["environment"],
                "specs": row["specs"],
                "fullServiceMapping": row.get("fullServiceMapping"),
                "mappedSkus": [item["sku"] for item in row["lineItems"]],
                "monthly": row["monthly"],
            }
        )
    compute_item = next((item for item in pricing.get("rateCard", []) if item.get("unit") == "OCPU-hour"), {"sku": "B97384"})
    memory_item = next((item for item in pricing.get("rateCard", []) if item.get("unit") == "GB-hour"), {"sku": "B97385"})
    mapping_rules = [
        {
            "sku": compute_item["sku"],
            "rule": "Uploaded spreadsheet CPU values are assumed to be vCPUs, converted to OCPUs in review using 2 vCPUs = 1 OCPU, then priced as OCPU-hours = OCPU x 730.",
        },
        {
            "sku": memory_item["sku"],
            "rule": "Memory GB-hours = memory GB x 730 using the selected flex shape rate.",
        },
        {"sku": "B91961", "rule": "VM local storage, database allocated storage, EBS, managed disks, persistent disks, SAN, and block volume rows use block volume GB-month."},
        {"sku": "B89057", "rule": "Shared/NAS storage, EFS, Azure Files, GCP Filestore, NFS, SMB, and file-share rows use file storage GB-month."},
    ]
    if pricing.get("fullServiceBeta"):
        mapping_rules.extend(
            [
                {"sku": "B91628", "rule": "S3, Blob, GCS, bucket, and standard object storage rows use object storage GB-month."},
                {"sku": "B91633", "rule": "Glacier, archive blob, archive/coldline, and backup archive rows use archive storage GB-month."},
                {"sku": "B91627", "rule": "S3/Blob/GCS request rows use object storage request units of 10,000 requests."},
            ]
        )
    return {
        "workflowContract": LLM_WORKFLOW_CONTRACT,
        "rowCount": len(pricing["rows"]),
        "totals": pricing["totals"],
        "sampleRows": sample_rows,
        "intakeMode": pricing.get("intakeMode", INTAKE_MODE_ON_PREM),
        "fullServiceBeta": pricing.get("fullServiceBeta", False),
        "selectedShape": pricing.get("selectedShape", shape_payload(DEFAULT_SHAPE_KEY)),
        "rateCard": pricing.get("rateCard", build_rate_card(DEFAULT_SHAPE_KEY)),
        "officialReferences": OCI_OFFICIAL_REFERENCES if pricing.get("fullServiceBeta") else [],
        "meteringGuidance": OCI_METERING_GUIDANCE if pricing.get("fullServiceBeta") else [],
        "sourceServiceMappings": provider_mapping_context("") if pricing.get("fullServiceBeta") else [],
        "priceCatalog": pricing.get("priceCatalog", []),
        "localMappingRules": mapping_rules,
    }


def describe_http_error(exc):
    payload = exc.read().decode("utf-8", errors="replace")
    try:
        error = json.loads(payload).get("error", {})
        parts = [str(exc)]
        if error.get("type"):
            parts.append(f"type={error.get('type')}")
        if error.get("code"):
            parts.append(f"code={error.get('code')}")
        if error.get("message"):
            parts.append(error.get("message"))
        return " | ".join(parts)
    except json.JSONDecodeError:
        return f"{exc} | {payload[:300]}"


def call_openai_json(
    system_content,
    user_payload,
    max_output_tokens=1600,
    timeout=45,
    model_env="OPENAI_MODEL",
    reasoning_effort_env=None,
    default_reasoning_effort=None,
):
    if not openai_api_enabled():
        return None, OPENAI_DISABLED_MESSAGE

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set."

    model = os.environ.get(model_env) or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    reasoning_effort = clean_text(os.environ.get(reasoning_effort_env)) if reasoning_effort_env else ""
    reasoning_effort = reasoning_effort or clean_text(default_reasoning_effort)
    body = {
        "model": model,
        "max_output_tokens": max_output_tokens,
        "input": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
    }
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = extract_response_text(payload)
        return parse_jsonish(text), None
    except urllib.error.HTTPError as exc:
        return None, describe_http_error(exc)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return None, str(exc)


def call_llm_workbook_plan(path, full_service_beta=False):
    digest = workbook_digest(path)
    system = (
        "You interpret Excel infrastructure inventory workbooks for an Oracle Cloud Infrastructure intake app. "
        "Your primary job is to find the workload identity and the specs needed for OCI pricing: core count, RAM/memory, and storage. "
        "Given workbook sheet samples, identify the sheet and row range that contain servers, applications, VMs, "
        "hosts, databases, or other infrastructure inventory. Return compact JSON only. "
        "Use 1-based row and column numbers. Do not invent missing columns. "
        "Map source columns to the provided canonical fields when the source appears equivalent, even if headings use "
        "terms like hostname, VM, instance, vCPU, RAM, disk, storage, OS, platform, environment, or application. "
        "Treat uploaded spreadsheet CPU/core values as vCPUs. The app will normalize those values to OCPUs for review "
        "using 2 vCPUs = 1 OCPU, so CPU/vCPU source columns should map to the OCPU canonical fields. "
        "Map RAM, Memory, MemoryGB, or MemoryGB(RAM) only to memory fields. Map Total Storage, Storage GB, allocated "
        "storage, disk size, or disk capacity to storage fields. Do not map a bare Disk/Disks column to storage or "
        "server count when its values look like small disk counts. If a storage heading says Total Storage, treat it "
        "as the row's total storage, not storage-per-server that should be multiplied by a disk count. "
        "Some workbooks, especially AWS billing or inventory exports, store tags as JSON strings in a cell. "
        "When a JSON/tag column contains useful keys, map it with jsonKey. For example, map tag key 'Name' or 'appId' "
        "to application_name, 'environment' to environment, and 'os' to application_details_operating_system. "
        "For application_details, prefer resource-specific values such as tag key 'appId', 'role', 'owner', resourceId, "
        "or private IP; avoid accountId or region unless nothing resource-specific exists. "
        "Do not map the full JSON blob as plain text unless no useful key exists. "
        "If each row is one server/VM/host, set serverGrain to 'server'. If each row is an application/workload "
        "that may represent many servers, set serverGrain to 'application'. "
        "Return this shape: {sheetName, headerRows, dataStartRow, dataEndRow, serverGrain, confidence, "
        "columnMappings:[{canonicalKey, sourceColumn, sourceHeader, jsonKey, confidence, transform}], notes:[string]}. "
        "For transform, briefly say unit conversions needed, such as TB to GB."
    )
    if full_service_beta:
        system += (
            " OCI full service beta is enabled. Treat AWS Cost Explorer/CUR exports, Azure cost exports, "
            "GCP billing exports, and on-prem CMDB/asset sheets as valid source workbooks even when they are not "
            "classic server inventories. Map provider, source service, source product/meter, source region, usage "
            "quantity, usage unit, and monthly cost columns when present. Prefer source_product for detailed usage "
            "type or meter names such as S3 StandardStorage, EBS VolumeUsage, Azure Blob Hot LRS, GCP Persistent Disk, "
            "NAS, SAN, backup archive, or object request rows. Use oci_service_category and oci_product only when "
            "the spreadsheet already contains target Oracle mapping columns; do not invent target values during "
            "column mapping."
        )
    payload = {
        "workflowContract": LLM_WORKFLOW_CONTRACT,
        "canonicalFields": canonical_field_prompt(full_service_beta),
        "ociFullServiceBeta": bool(full_service_beta),
        "ociPriceCatalog": price_catalog_payload() if full_service_beta else [],
        "workbook": digest,
    }
    plan, warning = call_openai_json(
        system,
        payload,
        max_output_tokens=2800,
        timeout=45,
        model_env="OPENAI_UPLOAD_MODEL",
    )
    if warning:
        if warning == OPENAI_DISABLED_MESSAGE:
            return None, "OpenAI API calls are temporarily disabled; used rule-based spreadsheet parsing."
        return None, f"OpenAI workbook interpretation did not complete; used rule-based spreadsheet parsing. Detail: {warning}"
    excel_file = pd.ExcelFile(path)
    normalized = normalize_workbook_plan(plan, excel_file, full_service_beta)
    if not normalized:
        return None, "OpenAI workbook interpretation did not identify a usable inventory table; used rule-based spreadsheet parsing."
    return normalized, None


def call_llm_mapping(pricing):
    prompt = compact_llm_summary(pricing)
    system = (
        "You are an Oracle Cloud Infrastructure pricing mapper. "
        "The rows you receive have already passed through the editable review table; treat those edited values as the source of truth. "
        "Validate whether the SKU mapping rules, selected OCI flexible compute shape, supplied OCI rate card, and any cloud-bill/on-prem "
        "service mappings are appropriate for the approved review-table rows. "
        "Return compact JSON only with keys globalAssumptions, mappingRules, and reviewNotes. "
        "Do not price from the original upload if review-table values differ. Do not invent rates. "
        "Do not recalculate every row; validate the rules against the supplied rate card and call out mapping risks."
    )
    payload, warning = call_openai_json(
        system,
        prompt,
        max_output_tokens=1200,
        timeout=45,
        model_env="OPENAI_PRICING_MODEL",
    )
    if warning:
        if warning == OPENAI_DISABLED_MESSAGE:
            return None, "OpenAI API calls are temporarily disabled; used deterministic SKU mapping."
        if warning == "OPENAI_API_KEY is not set.":
            return None, "OPENAI_API_KEY is not set; used deterministic SKU mapping."
        return None, f"OpenAI call did not complete; used deterministic SKU mapping. Detail: {warning}"
    return payload, None


def compact_table_edit_context(fields, rows, max_rows=250):
    editable_fields = [
        {
            "key": field.get("key"),
            "label": field.get("label") or field.get("key"),
            "description": field.get("description", ""),
        }
        for field in fields
        if field.get("key")
    ]
    row_payload = []
    for index, row in enumerate(rows[:max_rows], start=1):
        values = {}
        for field in editable_fields:
            key = field["key"]
            value = clean_cell(row.get(key, ""))
            if value != "":
                values[key] = value
        row_payload.append(
            {
                "displayIndex": index,
                "rowId": row.get("__id"),
                "sourceRow": row.get("__sourceRow"),
                "approved": row.get("__approved") is not False,
                "values": values,
            }
        )
    return {
        "fields": editable_fields,
        "rows": row_payload,
        "truncated": len(rows) > max_rows,
        "rowCount": len(rows),
        "includedRowCount": len(row_payload),
    }


def call_llm_table_edit(fields, rows, instruction, full_service_beta=False):
    system = (
        "You edit a normalized Oracle Cloud Infrastructure intake review table. Return compact JSON only. "
        "This table is the user's editable source of truth before pricing. Keep core/OCPU, RAM/memory, storage, application/workload, and environment fields coherent when the user asks for changes. "
        "Use only the provided rowId values and field key values when changing existing rows. "
        "If the user refers to row numbers, use displayIndex to choose the row. "
        "Never invent field keys. Do not change a value unless the user asked for that change or it is a direct consequence. "
        "For remove, exclude, ignore, or do-not-price requests, set that row's approval to false rather than deleting it. "
        "For new rows, return addRows with a values object keyed by known field keys. "
        "Return this exact shape: {summary:string, changes:[{rowId:string, fieldKey:string, value:string|number|boolean}], "
        "rowApprovals:[{rowId:string, approved:boolean}], addRows:[{values:object, approved:boolean}], warnings:[string]}."
    )
    payload = {
        "workflowContract": LLM_WORKFLOW_CONTRACT,
        "instruction": instruction,
        "ociFullServiceBeta": bool(full_service_beta),
        "table": compact_table_edit_context(fields, rows),
    }
    result, warning = call_openai_json(
        system,
        payload,
        max_output_tokens=2600,
        timeout=60,
        model_env="OPENAI_TABLE_EDIT_MODEL",
    )
    if warning:
        if warning == OPENAI_DISABLED_MESSAGE:
            return None, "OpenAI API calls are temporarily disabled; table assistant is unavailable."
        if warning == "OPENAI_API_KEY is not set.":
            return None, "OPENAI_API_KEY is not set; table assistant is unavailable."
        return None, f"OpenAI table edit did not complete. Detail: {warning}"
    return result, None


def coerce_approved(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = normalize(value)
    if text in {"false", "no", "0", "exclude", "excluded", "unapprove", "unapproved"}:
        return False
    if text in {"true", "yes", "1", "include", "included", "approve", "approved"}:
        return True
    return default


def apply_table_edit_plan(fields, rows, edit_plan):
    if not isinstance(edit_plan, dict):
        raise ValueError("The table assistant returned an invalid edit plan.")

    field_keys = [field.get("key") for field in fields if field.get("key")]
    field_key_set = set(field_keys)
    next_rows = [dict(row) for row in rows]
    next_lookup = {row.get("__id"): row for row in next_rows if row.get("__id")}
    applied = []
    warnings_list = [clean_text(item) for item in edit_plan.get("warnings", []) if clean_text(item)]

    for change in edit_plan.get("changes", []):
        if not isinstance(change, dict):
            continue
        row_id = clean_text(change.get("rowId"))
        field_key = clean_text(change.get("fieldKey"))
        if row_id not in next_lookup or field_key not in field_key_set:
            warnings_list.append(f"Skipped change for unknown row or field: {row_id} / {field_key}.")
            continue
        raw_value = change.get("value", "")
        value = normalize_inventory_value(field_key, raw_value)
        next_lookup[row_id][field_key] = value
        applied.append({"rowId": row_id, "fieldKey": field_key, "value": value})

    for approval in edit_plan.get("rowApprovals", []):
        if not isinstance(approval, dict):
            continue
        row_id = clean_text(approval.get("rowId"))
        if row_id not in next_lookup:
            warnings_list.append(f"Skipped approval update for unknown row: {row_id}.")
            continue
        approved = coerce_approved(approval.get("approved"), next_lookup[row_id].get("__approved") is not False)
        next_lookup[row_id]["__approved"] = approved
        applied.append({"rowId": row_id, "fieldKey": "__approved", "value": approved})

    for index, item in enumerate(edit_plan.get("addRows", []), start=1):
        if not isinstance(item, dict):
            continue
        values = item.get("values", {})
        if not isinstance(values, dict):
            continue
        new_row = {
            "__id": f"ai-{int(time.time() * 1000)}-{index}",
            "__sourceRow": "AI edit",
            "__approved": coerce_approved(item.get("approved"), True),
        }
        for field_key in field_keys:
            new_row[field_key] = ""
        for field_key, value in values.items():
            key = clean_text(field_key)
            if key in field_key_set:
                new_row[key] = normalize_inventory_value(key, value)
        next_rows.append(new_row)
        applied.append({"rowId": new_row["__id"], "fieldKey": "__new_row", "value": True})

    return {
        "rows": next_rows,
        "summary": clean_text(edit_plan.get("summary")) or f"Applied {len(applied)} table update(s).",
        "appliedChanges": applied,
        "warnings": warnings_list,
    }


def enrich_with_llm(pricing, llm_payload):
    if not llm_payload:
        return pricing
    mapping_by_row = {item.get("rowId"): item for item in llm_payload.get("mappings", [])}
    for row in pricing["rows"]:
        match = mapping_by_row.get(row["rowId"])
        if not match:
            continue
        row["llmMappedSkus"] = match.get("mappedSkus", [])
        row["llmAssumptions"] = match.get("assumptions", [])
    pricing["engine"] = "llm-assisted"
    pricing["globalAssumptions"] = llm_payload.get("globalAssumptions", [])
    pricing["mappingRules"] = llm_payload.get("mappingRules", [])
    pricing["reviewNotes"] = llm_payload.get("reviewNotes", [])
    return pricing


class IntakeHandler(BaseHTTPRequestHandler):
    server_version = "OCIIntake/1.0"

    def send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, status, message):
        self.send_json(status, {"error": message})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "openaiApiEnabled": openai_api_enabled(),
                    "openaiApiConfigured": openai_api_configured(),
                    "openaiApiConnected": openai_api_enabled() and openai_api_configured(),
                    "openaiModel": os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
                    "rateCard": build_rate_card(DEFAULT_SHAPE_KEY),
                    "rateCards": all_shape_payloads(),
                    "selectedShape": shape_payload(DEFAULT_SHAPE_KEY),
                    "fullServiceCatalog": price_catalog_payload(),
                },
            )
            return
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html")
            return
        if path.startswith("/static/"):
            target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self.send_error_json(403, "Invalid static path.")
                return
            self.serve_file(target)
            return
        self.send_error_json(404, "Not found.")

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error_json(404, "File not found.")
            return
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload":
            self.handle_upload()
            return
        if parsed.path == "/api/price":
            self.handle_price()
            return
        if parsed.path == "/api/edit-table":
            self.handle_table_edit()
            return
        if parsed.path == "/api/export":
            self.handle_export()
            return
        self.send_error_json(404, "Not found.")

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error_json(400, "Upload must be multipart/form-data.")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        if "file" not in form:
            self.send_error_json(400, "Missing file field.")
            return

        file_item = form["file"]
        intake_mode = normalize_intake_mode(form.getvalue("intakeMode"))
        provider_hint = normalize_provider_hint(form.getvalue("providerHint"))
        full_service_beta = (
            intake_mode == INTAKE_MODE_CLOUD_BILL
            or clean_text(form.getvalue("fullServiceBeta")).lower() in {"1", "true", "yes", "on"}
        )
        filename = clean_text(getattr(file_item, "filename", "")) or "upload.xlsx"
        allowed_suffixes = (".xlsx", ".xls", ".csv", ".tsv", ".pdf") if intake_mode == INTAKE_MODE_CLOUD_BILL else (".xlsx", ".xls")
        if not filename.lower().endswith(allowed_suffixes):
            message = "Please upload a PDF, CSV, TSV, or Excel bill export." if intake_mode == INTAKE_MODE_CLOUD_BILL else "Please upload an Excel workbook."
            self.send_error_json(400, message)
            return

        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
        saved_path = UPLOAD_DIR / f"{int(time.time())}_{safe_name}"
        saved_path.write_bytes(file_item.file.read())

        try:
            parsed = parse_workbook(saved_path, full_service_beta, intake_mode, provider_hint)
            parsed["fileName"] = filename
            parsed["uploadedPath"] = str(saved_path)
            self.send_json(200, parsed)
        except Exception as exc:
            self.send_error_json(500, f"Could not parse workbook: {exc}")

    def handle_price(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            fields = payload.get("fields", [])
            rows = payload.get("rows", [])
            shape_key = payload.get("shape") or DEFAULT_SHAPE_KEY
            intake_mode = normalize_intake_mode(payload.get("intakeMode"))
            full_service_beta = bool(payload.get("fullServiceBeta")) or intake_mode == INTAKE_MODE_CLOUD_BILL
            bom_match = bool(payload.get("bomMatch"))
            hide_gpu_pricing = bool(payload.get("hideGpuPricing"))
            hide_windows_pricing = bool(payload.get("hideWindowsPricing"))
            rightsize = bool(payload.get("rightsize"))
            if shape_key not in SHAPE_LOOKUP:
                self.send_error_json(400, f"Unsupported OCI flex shape: {shape_key}")
                return
            if not fields or not rows:
                self.send_error_json(400, "Pricing requires fields and rows.")
                return
            pricing = calculate_pricing(fields, rows, shape_key, full_service_beta, intake_mode, bom_match, hide_gpu_pricing, hide_windows_pricing, rightsize)
            pricing["bomMatch"] = bom_match
            pricing["hideGpuPricing"] = hide_gpu_pricing
            pricing["hideWindowsPricing"] = hide_windows_pricing
            pricing["rightsize"] = rightsize
            llm_payload, llm_warning = call_llm_mapping(pricing)
            pricing = enrich_with_llm(pricing, llm_payload)
            if llm_warning:
                pricing["llmWarning"] = llm_warning
            self.send_json(200, pricing)
        except Exception as exc:
            self.send_error_json(500, f"Could not price inventory: {exc}")

    def handle_export(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            fields = payload.get("fields", [])
            rows = payload.get("rows", [])
            shape_key = payload.get("shape") or DEFAULT_SHAPE_KEY
            intake_mode = normalize_intake_mode(payload.get("intakeMode"))
            full_service_beta = bool(payload.get("fullServiceBeta")) or intake_mode == INTAKE_MODE_CLOUD_BILL
            bom_match = bool(payload.get("bomMatch"))
            hide_gpu_pricing = bool(payload.get("hideGpuPricing"))
            hide_windows_pricing = bool(payload.get("hideWindowsPricing"))
            rightsize = bool(payload.get("rightsize"))
            ramp = payload.get("ramp")
            existing_infra_cost = payload.get("existingInfraCost", 0)
            if shape_key not in SHAPE_LOOKUP:
                self.send_error_json(400, f"Unsupported OCI flex shape: {shape_key}")
                return
            if not fields or not rows:
                self.send_error_json(400, "Export requires fields and rows.")
                return
            pricing = calculate_pricing(fields, rows, shape_key, full_service_beta, intake_mode, bom_match, hide_gpu_pricing, hide_windows_pricing, rightsize)
            servers = bom_export.servers_from_pricing(pricing, rows)
            shape = pricing.get("selectedShape") or {}
            shape_for_export = {
                "label": shape.get("shortLabel") or shape.get("label"),
                "shortLabel": shape.get("shortLabel") or shape.get("label"),
                "computeSku": shape.get("computeSku"),
                "memorySku": shape.get("memorySku"),
                "computeRate": shape.get("computeRate"),
                "memoryRate": shape.get("memoryRate"),
            }
            content = bom_export.build_workbook_bytes(servers, ramp, existing_infra_cost, shape_for_export, hide_windows_pricing)
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", 'attachment; filename="OCI_BOM_Export.xlsx"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.send_error_json(500, f"Could not export workbook: {exc}")

    def handle_table_edit(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            instruction = clean_text(payload.get("instruction"))
            fields = payload.get("fields", [])
            rows = payload.get("rows", [])
            intake_mode = normalize_intake_mode(payload.get("intakeMode"))
            full_service_beta = bool(payload.get("fullServiceBeta")) or intake_mode == INTAKE_MODE_CLOUD_BILL

            if not instruction:
                self.send_error_json(400, "Tell the table what to change first.")
                return
            if len(instruction) > 4000:
                self.send_error_json(400, "Please keep table edit instructions under 4,000 characters.")
                return
            if not fields or not rows:
                self.send_error_json(400, "Table edits require fields and rows.")
                return

            edit_plan, edit_warning = call_llm_table_edit(fields, rows, instruction, full_service_beta)
            if edit_warning:
                self.send_error_json(502, edit_warning)
                return

            edited = apply_table_edit_plan(fields, rows, edit_plan)
            self.send_json(200, edited)
        except Exception as exc:
            self.send_error_json(500, f"Could not edit table: {exc}")

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), IntakeHandler)
    print(f"OCI Intake app running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
