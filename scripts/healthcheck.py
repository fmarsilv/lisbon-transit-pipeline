"""One-command health check for the vehicles pipeline.

Answers: is it switched on, is the deployed function what we expect, is data arriving,
is it complete, is it failing, and what is it costing?

Usage (from the repo root, logged in with `aws sso login`):
    AWS_PROFILE=transit uv run python scripts/healthcheck.py

Exit code is 0 when every check passes and 1 otherwise, so it can run in CI or cron later.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from _config import setting

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
ICONS = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌"}
VEHICLES_PREFIX = "raw/carris/vehicles"


def check_schedule(scheduler, schedule_name):
    state = scheduler.get_schedule(Name=schedule_name)["State"]
    return (PASS if state == "ENABLED" else FAIL), f"schedule is {state}"


def check_function(lambda_client, function_name):
    cfg = lambda_client.get_function_configuration(FunctionName=function_name)
    detail = f"{cfg['Runtime']}, {cfg['Architectures'][0]}, {cfg['MemorySize']} MB, last deployed {cfg['LastModified'][:16]}"
    expected = cfg["Runtime"] == "python3.12" and cfg["MemorySize"] == 256
    return (PASS if expected else WARN), detail


def hour_prefix(ts: datetime) -> str:
    return f"{VEHICLES_PREFIX}/dt={ts:%Y-%m-%d}/hour={ts:%H}/"


def list_keys(s3, bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    return [obj for page in paginator.paginate(Bucket=bucket, Prefix=prefix) for obj in page.get("Contents", [])]


def check_freshness(s3, bucket, now):
    # Look in this hour and the previous one, so the check also works just after midnight or the top of the hour.
    objects = list_keys(s3, bucket, hour_prefix(now)) + list_keys(s3, bucket, hour_prefix(now - timedelta(hours=1)))
    if not objects:
        return FAIL, "no files in the last two hours"
    newest = max(obj["LastModified"] for obj in objects)
    age = (now - newest).total_seconds()
    status = PASS if age <= 180 else WARN if age <= 600 else FAIL
    return status, f"newest file is {age:.0f}s old"


def check_last_full_hour(s3, bucket, now):
    last_hour = now - timedelta(hours=1)
    count = len(list_keys(s3, bucket, hour_prefix(last_hour)))
    status = PASS if count == 60 else WARN if count >= 55 else FAIL
    return status, f"{count}/60 files in {last_hour:%Y-%m-%d %H}:00 UTC"


def check_errors(logs, log_group, now):
    start_ms = int((now - timedelta(hours=24)).timestamp() * 1000)
    paginator = logs.get_paginator("filter_log_events")
    events = [
        event
        for page in paginator.paginate(logGroupName=log_group, startTime=start_ms, filterPattern='?ERROR ?"Task timed out"')
        for event in page.get("events", [])
    ]
    return (PASS if not events else FAIL), f"{len(events)} error/timeout log lines in the last 24h"


def check_spend(budgets, account_id):
    budget = budgets.describe_budgets(AccountId=account_id)["Budgets"][0]
    spent = float(budget["CalculatedSpend"]["ActualSpend"]["Amount"])
    limit = float(budget["BudgetLimit"]["Amount"])
    status = PASS if spent < 0.5 * limit else WARN if spent < 0.8 * limit else FAIL
    return status, f"${spent:.2f} of ${limit:.2f} this month"


def main() -> int:
    import boto3  # imported here so the pure helpers above can be tested without AWS installed

    bucket = setting("RAW_BUCKET", "raw_bucket_name")
    function_name = setting("VEHICLES_FUNCTION", "vehicles_function_name")
    log_group = setting("VEHICLES_LOG_GROUP", "vehicles_log_group")
    schedule_name = setting("VEHICLES_SCHEDULE", "vehicles_schedule_name")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    now = datetime.now(timezone.utc)

    checks = [
        ("Schedule", lambda: check_schedule(boto3.client("scheduler"), schedule_name)),
        ("Function", lambda: check_function(boto3.client("lambda"), function_name)),
        ("Freshness", lambda: check_freshness(boto3.client("s3"), bucket, now)),
        ("Completeness", lambda: check_last_full_hour(boto3.client("s3"), bucket, now)),
        ("Errors", lambda: check_errors(boto3.client("logs"), log_group, now)),
        ("Spend", lambda: check_spend(boto3.client("budgets"), account_id)),
    ]

    print(f"Vehicles pipeline health check, {now:%Y-%m-%d %H:%M} UTC\n")
    worst = PASS
    for name, run in checks:
        try:
            status, detail = run()
        except Exception as exc:  # one broken check shouldn't hide the others
            status, detail = FAIL, f"check itself failed: {exc}"
        print(f"{ICONS[status]} {name:<13} {detail}")
        if status == FAIL or (status == WARN and worst == PASS):
            worst = status

    print(f"\nOverall: {worst}")
    return 0 if worst == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
