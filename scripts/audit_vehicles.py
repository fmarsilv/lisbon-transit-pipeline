"""Audit everything the vehicles poller has collected: completeness, gaps and real volumes.

Where healthcheck.py asks "is it working right now?", this asks "how reliable has it been,
and how much data does it really produce?" It turns the estimates in decisions 009 and 015
into measurements.

Usage (from the repo root):
    AWS_PROFILE=transit uv run python scripts/audit_vehicles.py --since 2026-10-26T09:00
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from _config import setting

PREFIX = "raw/carris/vehicles/"
KEY_TIMESTAMP = re.compile(r"vehicles_(\d{8}T\d{6})Z\.json\.gz$")
GAP_THRESHOLD = timedelta(seconds=90)  # two runs more than 90s apart means at least one minute was missed
EXTRA_THRESHOLD = timedelta(seconds=30)  # two runs closer than 30s means an extra run (e.g. a manual invoke)


def parse_timestamp(key: str) -> datetime | None:
    """Extract the fetch time from a raw key, e.g. ...vehicles_20261026T085238Z.json.gz."""
    match = KEY_TIMESTAMP.search(key)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def summarise(objects: list[dict], since: datetime | None = None) -> tuple[list[dict], list[tuple[datetime, datetime, int]], int, list[str]]:
    """Turn a list of S3 objects ({"Key", "Size"}) into per-day stats, gaps, extra runs and unparseable keys.

    Pure function: no AWS calls, so it can be tested with made-up data.
    """
    rows, skipped = [], []
    for obj in objects:
        ts = parse_timestamp(obj["Key"])
        if ts is None:
            skipped.append(obj["Key"])
        elif since is None or ts >= since:
            rows.append((ts, obj["Size"]))
    rows.sort()
    if not rows:
        return [], [], 0, skipped

    # Gaps: consecutive runs further apart than the threshold. Missed runs ~ minutes between them, minus one.
    gaps = []
    for (prev, _), (curr, _) in zip(rows, rows[1:]):
        if curr - prev > GAP_THRESHOLD:
            gaps.append((prev, curr, round((curr - prev).total_seconds() / 60) - 1))
    extras = sum(1 for (prev, _), (curr, _) in zip(rows, rows[1:]) if curr - prev < EXTRA_THRESHOLD)

    # Per-day volumes. Expected runs = minutes covered that day (first and last days are partial).
    by_day = defaultdict(list)
    for ts, size in rows:
        by_day[ts.date()].append((ts, size))
    days = []
    for day, items in sorted(by_day.items()):
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        window_start = max(day_start, rows[0][0].replace(second=0))
        window_end = min(day_start + timedelta(days=1), rows[-1][0].replace(second=0) + timedelta(minutes=1))
        expected = int((window_end - window_start).total_seconds() // 60)
        total = sum(size for _, size in items)
        days.append({
            "day": day,
            "files": len(items),
            "expected": expected,
            "completeness": len(items) / expected if expected else 0.0,
            "total_mb": total / 1e6,
            "avg_kb": total / len(items) / 1e3,
            "partial": expected < 1440,
        })
    return days, gaps, extras, skipped


def main() -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="only audit files from this UTC time on, e.g. 2026-10-26T09:00 (the go-live)")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None

    bucket = setting("RAW_BUCKET", "raw_bucket_name")
    paginator = boto3.client("s3").get_paginator("list_objects_v2")
    objects = [obj for page in paginator.paginate(Bucket=bucket, Prefix=PREFIX) for obj in page.get("Contents", [])]
    if not objects:
        print("No vehicle files found.")
        return 1

    days, gaps, extras, skipped = summarise(objects, since)
    if not days:
        print("No vehicle files in the selected period.")
        return 1

    audited = sum(d["files"] for d in days)
    period = f" since {since:%Y-%m-%d %H:%M} UTC" if since else ""
    print(f"Vehicles raw layer audit: {audited:,} files{period} in s3://{bucket}/{PREFIX}\n")
    print(f"{'Day (UTC)':<12} {'Weekday':<9} {'Files':>6} {'Expected':>9} {'Complete':>9} {'MB (gz)':>9} {'Avg KB':>8}")
    for d in days:
        note = "  (partial day)" if d["partial"] else ""
        print(f"{d['day']!s:<12} {d['day']:%a}{'':<6} {d['files']:>6} {d['expected']:>9} "
              f"{d['completeness']:>8.1%} {d['total_mb']:>9.1f} {d['avg_kb']:>8.1f}{note}")

    full_days = [d for d in days if not d["partial"]]
    if full_days:
        avg_mb = sum(d["total_mb"] for d in full_days) / len(full_days)
        print(f"\nAverage full day: {avg_mb:.0f} MB gzipped, about {avg_mb * 30 / 1e3:.1f} GB a month")

    print(f"\nGaps (runs more than {GAP_THRESHOLD.seconds}s apart): {len(gaps)}")
    for prev, curr, missed in gaps[:20]:
        print(f"  {prev:%Y-%m-%d %H:%M:%S} -> {curr:%H:%M:%S} UTC  (~{missed} missed run{'s' if missed != 1 else ''})")
    if len(gaps) > 20:
        print(f"  ... and {len(gaps) - 20} more")

    print(f"\nExtra runs (less than {EXTRA_THRESHOLD.seconds}s after the previous one, e.g. manual invokes): {extras}")

    if skipped:
        print(f"\nKeys that don't match the naming pattern: {len(skipped)} (first: {skipped[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
