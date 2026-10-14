"""Shared helpers for all ingestion jobs: HTTP fetching, raw-layer key naming, and writing files.

Every poller (vehicles, weather, stops, ...) reuses these, so the behaviour of the raw
layer is defined in exactly one place.
"""
from __future__ import annotations

import functools
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Identifies us politely to the API owners. Replace <your-github-user> with your username.
USER_AGENT = "lisbon-transit-pipeline/0.1 (portfolio project; github.com/fmarsilv/lisbon-transit-pipeline)"


def fetch_bytes(url: str, timeout: int = 15, attempts: int = 3, backoff_seconds: float = 2.0) -> bytes:
    """GET a URL and return the response body as raw bytes.

    Retries transient failures (network errors, timeouts, HTTP 5xx) with a growing wait.
    Client errors (HTTP 4xx) are raised immediately, because retrying a bad request won't fix it.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts:
                raise
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            error = exc

        wait = backoff_seconds * attempt
        logger.warning("Attempt %d/%d failed for %s (%s); retrying in %.0fs", attempt, attempts, url, error, wait)
        time.sleep(wait)

    raise RuntimeError("unreachable")  # the loop always returns or raises


def build_raw_key(source: str, name: str, fetched_at: datetime, hourly: bool = False, extension: str = "json.gz") -> str:
    """Build the raw-layer path for one fetched file.

    Example (hourly=True):
        raw/carris/vehicles/dt=2026-10-05/hour=17/vehicles_20261005T172800Z.json.gz

    Partitions use the UTC *ingestion* time, which is always known, rather than any
    timestamp inside the payload, which we only trust after cleaning it in dbt.
    """
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware (e.g. datetime.now(timezone.utc))")

    ts = fetched_at.astimezone(timezone.utc)
    parts = ["raw", source, name, f"dt={ts:%Y-%m-%d}"]
    if hourly:
        parts.append(f"hour={ts:%H}")
    parts.append(f"{name}_{ts:%Y%m%dT%H%M%SZ}.{extension}")
    return "/".join(parts)


@functools.lru_cache(maxsize=1)
def _s3_client():
    """Create the S3 client once and reuse it.

    Lambda keeps a function's environment alive between invocations ("warm starts"),
    so caching the client avoids rebuilding it every minute.
    """
    import boto3  # imported here so purely local runs don't need boto3 configured

    return boto3.client("s3")


def write_raw(body: bytes, key: str, content_type: str = "application/gzip") -> str:
    """Write bytes to the raw layer and return where they ended up.

    - If the RAW_BUCKET environment variable is set, write to that S3 bucket.
    - Otherwise write to a local folder (LOCAL_OUTPUT_DIR, default ./local_raw),
      which lets us test the whole job on a laptop with no AWS involved.
    """
    bucket = os.environ.get("RAW_BUCKET")
    if bucket:
        _s3_client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        return f"s3://{bucket}/{key}"

    path = Path(os.environ.get("LOCAL_OUTPUT_DIR", "local_raw")) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)
