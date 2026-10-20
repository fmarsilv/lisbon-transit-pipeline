"""Unit tests for raw-layer key naming. Getting partitions wrong silently misfiles data, so we pin it down."""
from datetime import datetime, timedelta, timezone

import pytest

from ingestion.common import build_raw_key


def test_hourly_key_layout():
    ts = datetime(2026, 10, 5, 17, 28, 0, tzinfo=timezone.utc)
    assert (
        build_raw_key("carris", "vehicles", ts, hourly=True)
        == "raw/carris/vehicles/dt=2026-10-05/hour=17/vehicles_20261005T172800Z.json.gz"
    )


def test_daily_key_has_no_hour_partition():
    ts = datetime(2026, 10, 5, 3, 0, 0, tzinfo=timezone.utc)
    assert build_raw_key("carris", "stops", ts) == "raw/carris/stops/dt=2026-10-05/stops_20261005T030000Z.json.gz"


def test_non_utc_time_is_converted_to_utc_partition():
    # 00:30 on Oct 6 in Lisbon summer time (UTC+1) is still 23:30 on Oct 5 in UTC.
    lisbon_summer = timezone(timedelta(hours=1))
    ts = datetime(2026, 10, 6, 0, 30, 0, tzinfo=lisbon_summer)
    assert build_raw_key("carris", "vehicles", ts, hourly=True).startswith("raw/carris/vehicles/dt=2026-10-05/hour=23/")


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        build_raw_key("carris", "vehicles", datetime(2026, 10, 5, 17, 0, 0))
