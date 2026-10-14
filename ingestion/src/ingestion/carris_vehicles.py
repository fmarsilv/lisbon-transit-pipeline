"""Poll Carris Metropolitana live vehicle positions and land the raw response in the raw layer.

Runs every minute on AWS Lambda (triggered by EventBridge Scheduler), or locally with:
    PYTHONPATH=ingestion/src uv run python -m ingestion.carris_vehicles
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone

from ingestion.common import build_raw_key, fetch_bytes, write_raw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

VEHICLES_URL = "https://api.carrismetropolitana.pt/v2/vehicles"


def handler(event=None, context=None) -> dict:
    """Lambda entry point. AWS calls this with (event, context); we don't need either."""
    fetched_at = datetime.now(timezone.utc)
    raw = fetch_bytes(VEHICLES_URL)

    # Sanity check before storing: the response must be a JSON list.
    # We validate the parsed copy but store the original bytes, so the raw layer stays untouched.
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list from {VEHICLES_URL}, got {type(payload).__name__}")
    if not payload:
        logger.warning("Vehicles feed returned an empty list (normal in the small hours, suspicious by day)")

    key = build_raw_key("carris", "vehicles", fetched_at, hourly=True)
    location = write_raw(gzip.compress(raw), key)

    summary = {
        "source": "carris_vehicles",
        "fetched_at": fetched_at.isoformat(),
        "vehicle_count": len(payload),
        "raw_bytes": len(raw),
        "location": location,
    }
    logger.info(json.dumps(summary))  # one JSON line per run: easy to search in CloudWatch Logs
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(handler(), indent=2))
