"""Live AWS on-demand pricing via the AWS Price List Query API (pricing:GetProducts).

Used to price the AWS side of the cross-cloud estimate with real, current rates.
Credentials come from the standard AWS chain (env vars, ~/.aws/credentials, or an
instance role) - they are never stored by or exposed to this app. The Query API
endpoint lives only in us-east-1 / ap-south-1 but returns pricing for all regions.

Everything here fails soft: if boto3 isn't installed, there are no credentials, or
a lookup misses, the caller falls back to the bundled/estimated rates.
"""

import json
import os
import threading
from pathlib import Path

try:
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError  # type: ignore
    _BOTO_IMPORT_OK = True
except Exception:  # boto3 not installed
    _BOTO_IMPORT_OK = False

# Allow turning the live API off without uninstalling boto3.
AWS_PRICING_ENABLED = os.environ.get("AWS_PRICING_API", "1").lower() not in {"0", "false", "off", "no"}

_CACHE_PATH = Path(__file__).resolve().parent / "data" / "aws_price_cache.json"
_LOCK = threading.Lock()
_client = None
_client_tried = False
_cache = None

# AWS region code -> Price List "location" name.
REGION_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-central-2": "EU (Zurich)",
    "eu-north-1": "EU (Stockholm)",
    "eu-south-1": "EU (Milan)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "sa-east-1": "South America (Sao Paulo)",
    "me-south-1": "Middle East (Bahrain)",
    "af-south-1": "Africa (Cape Town)",
}
DEFAULT_LOCATION = "US East (N. Virginia)"


def location_for_region(region):
    """Map a region code (or a value that already is a location name) to a location."""
    if not region:
        return DEFAULT_LOCATION
    text = str(region).strip()
    if text in REGION_LOCATION:
        return REGION_LOCATION[text]
    if text in REGION_LOCATION.values():
        return text
    return REGION_LOCATION.get(text.lower(), DEFAULT_LOCATION)


def _load_cache():
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(_CACHE_PATH.read_text())
    except Exception:
        _cache = {}
    return _cache


def _save_cache():
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_cache, indent=0))
    except Exception:
        pass


def _get_client():
    global _client, _client_tried
    if _client is not None or _client_tried:
        return _client
    _client_tried = True
    if not (_BOTO_IMPORT_OK and AWS_PRICING_ENABLED):
        return None
    try:
        _client = boto3.client(
            "pricing",
            region_name="us-east-1",
            config=Config(connect_timeout=4, read_timeout=8, retries={"max_attempts": 2}),
        )
    except Exception:
        _client = None
    return _client


_creds_ok = None


def available():
    """True if the live API can be attempted: boto3 present, enabled, client built,
    and AWS credentials resolvable from the standard chain."""
    global _creds_ok
    if _get_client() is None:
        return False
    if _creds_ok is None:
        try:
            _creds_ok = boto3.session.Session().get_credentials() is not None
        except Exception:
            _creds_ok = False
    return bool(_creds_ok)


def _parse_memory_gib(value):
    """'16 GiB' -> 16.0."""
    try:
        return float(str(value).split()[0].replace(",", ""))
    except (ValueError, IndexError, AttributeError):
        return None


def instance_specs(instance_type, region=None):
    """Return {'rate': $/hr, 'vcpu': float, 'memoryGb': float} for an EC2 instance
    type (on-demand Linux), or None. Fills sizing the source bill often lacks.
    Cached (including misses) so repeated runs don't re-hit the API."""
    if not instance_type:
        return None
    location = location_for_region(region)
    cache = _load_cache()
    key = f"{instance_type}|{location}"
    if key in cache:
        val = cache[key]
        if not val:
            return None
        return val if isinstance(val, dict) else {"rate": val, "vcpu": None, "memoryGb": None}

    client = _get_client()
    if client is None:
        return None

    result = None
    try:
        resp = client.get_products(
            ServiceCode="AmazonEC2",
            MaxResults=1,
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": str(instance_type)},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            ],
        )
        for item in resp.get("PriceList", []):
            product = json.loads(item) if isinstance(item, str) else item
            attrs = (product.get("product", {}) or {}).get("attributes", {}) or {}
            vcpu = None
            try:
                vcpu = float(attrs.get("vcpu")) if attrs.get("vcpu") else None
            except (TypeError, ValueError):
                vcpu = None
            mem = _parse_memory_gib(attrs.get("memory"))
            rate = None
            on_demand = (product.get("terms", {}) or {}).get("OnDemand", {}) or {}
            for term in on_demand.values():
                for dim in (term.get("priceDimensions", {}) or {}).values():
                    usd = (dim.get("pricePerUnit", {}) or {}).get("USD")
                    try:
                        v = float(usd)
                    except (TypeError, ValueError):
                        continue
                    if v > 0:
                        rate = v
                        break
                if rate is not None:
                    break
            if rate is not None or vcpu or mem:
                result = {"rate": rate, "vcpu": vcpu, "memoryGb": mem}
                break
    except (NoCredentialsError, ClientError, BotoCoreError, Exception):
        result = None

    with _LOCK:
        cache[key] = result if result else 0
        _save_cache()
    return result


def ondemand_linux_rate(instance_type, region=None):
    """On-demand Linux $/hour for an EC2 instance type, or None."""
    specs = instance_specs(instance_type, region)
    return specs.get("rate") if specs else None


def service_sku(service_code, usage_type, region=None):
    """Look up the AWS product SKU (and rate/unit) for any service line by its
    ServiceCode (the bill's ProductCode, e.g. 'AWSLambda', 'AmazonS3') and usageType.
    Returns {'sku', 'rate', 'unit'} or None. Cached, including misses."""
    if not service_code or not usage_type:
        return None
    cache = _load_cache()
    key = f"SKU|{service_code}|{usage_type}"
    if key in cache:
        val = cache[key]
        return val if val else None
    client = _get_client()
    if client is None:
        return None
    result = None
    try:
        resp = client.get_products(
            ServiceCode=str(service_code),
            MaxResults=1,
            Filters=[{"Type": "TERM_MATCH", "Field": "usagetype", "Value": str(usage_type)}],
        )
        for item in resp.get("PriceList", []):
            product = json.loads(item) if isinstance(item, str) else item
            sku = (product.get("product", {}) or {}).get("sku")
            rate = None
            unit = None
            on_demand = (product.get("terms", {}) or {}).get("OnDemand", {}) or {}
            for term in on_demand.values():
                for dim in (term.get("priceDimensions", {}) or {}).values():
                    unit = dim.get("unit") or unit
                    usd = (dim.get("pricePerUnit", {}) or {}).get("USD")
                    try:
                        rate = float(usd)
                    except (TypeError, ValueError):
                        pass
                    if rate is not None:
                        break
                if rate is not None:
                    break
            if sku:
                result = {"sku": sku, "rate": rate, "unit": unit}
                break
    except (NoCredentialsError, ClientError, BotoCoreError, Exception):
        result = None
    with _LOCK:
        cache[key] = result if result else 0
        _save_cache()
    return result
