# Design Decisions

A running log of findings and choices made while building this pipeline.

## 001 — Use Carris Metropolitana API v2

- **Context:** API v1 is being deprecated.
- **Decision:** Build against `https://api.carrismetropolitana.pt/v2`.

## 002 — Vehicle timestamps are UTC epoch milliseconds

- **Finding:** `/vehicles` timestamps are 13 digits (milliseconds). The README example shows seconds and claims values are "adjusted for Lisbon time", but comparing against the system clock shows they are true UTC epoch values.
- **Decision:** Convert in staging with `to_timestamp(timestamp / 1000)` and treat as UTC. Add a dbt test asserting timestamps fall within a plausible range.

## 003 — IDs carry bracketed plan/version prefixes

- **Finding:** Live IDs differ from the documented format, e.g. trip `[F34NX][YA15B]3512_0_1_1700_1729_0_ESC_DOM`, pattern `[YA15B]3508_2_2`. The GTFS feed uses the same convention (`[VNWG3][LA77N]1001_0_1_0600_0629_0_1`), and ships a non-standard `plans.txt`.
- **Decision:** Keep IDs exactly as published and join on the full ID. URL-encode IDs in API calls (brackets break naive URL handling, e.g. curl globbing).

## 004 — Derive observed arrivals from vehicle positions, not the Arrivals endpoint

- **Finding:** `/arrivals/by_stop` returns the day's schedule, but `observed_arrival` was null for 37/37 past arrivals at a sampled stop. `/arrivals/by_pattern` returned 404 for every ID format tried.
- **Decision:** Poll `/vehicles` frequently and derive arrival events from `STOPPED_AT` pings. Compute delay against the GTFS schedule (`stop_times.txt`).

## 005 — Vehicle trip IDs join directly to GTFS

- **Finding:** A live vehicle `trip_id` (full, with prefixes) matched exactly one row in `trips.txt`.
- **Decision:** Join vehicles → `stop_times` on (`trip_id`, `stop_id`). Watch for loop routes that visit the same stop twice in one trip.

## 006 — GTFS static feed is large

- **Finding:** ~70 MB zipped; `stop_times.txt` alone is ~787 MB unzipped.
- **Decision:** Don't unzip inside Lambda `/tmp` (512 MB default). Land the zip in S3 as-is and handle extraction separately.

## 007 — IPMA observations must be captured continuously

- **Finding:** The observations feed is a rolling ~24h window with no archive.
- **Decision:** Poll hourly; missed hours are unrecoverable.

## 008 — Endpoint inventory and collection cadence

- **Finding:** All candidate v2 endpoints return HTTP 200. Sizes range from <1 KB (`metrics/videowall/delays`) to ~48 MB (`metrics/demand/by_line`, which returns full history on every call).
- **Decision:** Poll small live endpoints frequently (delays every 15 min, alerts every 30 min), dimensions daily (`stops`, `lines`, `routes`), rolling-window metrics daily (`metrics/service/all`, 14-day window), and full-history demand weekly. Municipalities are loaded once as a dbt seed. Skip `/arrivals`, `/patterns`, `/shapes` (empty or duplicated by GTFS).

## 009 — Raw layer layout and polling interval

- **Finding:** A vehicles snapshot is ~327 KB (~450–500 vehicles). Polling every minute gives ~700k rows/day (~20M/month) and ~50 MB/day gzipped.
- **Decision:** Poll vehicles every 1 minute (EventBridge minimum). Store raw API responses unmodified and gzipped in S3, Hive-partitioned by UTC ingestion time (`dt=`, `hour=`), one timestamped file per poll for idempotent retries.

## 010 — Weather: nearest IPMA station per bus stop

- **Finding:** Carris Metropolitana operates in the municipalities around Lisbon, not inside Lisbon city, so "Lisboa" stations alone are unrepresentative. A bounding box over the metropolitan area returns 18 IPMA stations (Setúbal, Almada, Barreiro, Amadora, Sintra, Oeiras, Alcochete, etc.). It also includes edge cases: Torres Vedras (outside the area) and exposed coastal capes (Cabo da Roca, Cabo Raso).
- **Finding:** `observations.json` is nested by dynamic keys: hour timestamp (e.g. `2026-10-04T17:00`, no timezone suffix) → station ID → readings with Portuguese field names (`temperatura`, `humidade`, `precAcumulada`, `intensidadeVento`, ...). Each poll returns the full rolling ~24h window (24 hourly keys). Timestamps are UTC: at 17:11 UTC the newest key was `16:00`, i.e. data is published with ~1 hour lag.
- **Decision:** Ingest all stations raw; in dbt, flatten twice (hour, then station), rename fields to English, convert `-99` sentinels to null, and deduplicate on (`station_id`, `observed_at`) since consecutive hourly polls overlap by ~23 hours. Parse hour keys as UTC and schedule the hourly poll at :30 past the hour to allow for the publishing lag. Map each bus stop to its nearest station by distance, with a flag to exclude unrepresentative stations.

## 011 — Infrastructure as code with Terraform

- **Context:** The raw-layer bucket is the first cloud resource; everything else (Lambda, IAM, schedules, Snowflake) will follow.
- **Decision:** Manage all AWS infrastructure with Terraform in `infra/`, never by hand in the console. The AWS provider is pinned to `~> 6.0` and `.terraform.lock.hcl` is committed for reproducible runs. All resources carry `Project` and `ManagedBy = terraform` tags.
- **Decision:** The raw bucket blocks all public access, encrypts at rest (SSE-S3), and has `force_destroy = false` so Terraform cannot delete it while it holds data. The bucket name includes the account ID, looked up at run time so it is never committed.
- **Decision:** Authenticate with short-lived IAM Identity Center (SSO) credentials via the `transit` profile, not long-lived access keys.
- **Trade-off:** Terraform state is local for now (gitignored, never committed). Acceptable for a single developer; state moves to an S3 backend before CI needs to run Terraform.

## 012 — Account budget alarm

- **Decision:** A `$5`/month AWS cost budget, managed in Terraform (`infra/budgets.tf`), emails on actual spend above 80% and on forecast spend above 100%. The forecast alert fires before money is spent.
- **Note:** A budget alerts, it never blocks spending; billing data lags by hours. The alert email lives in `terraform.tfvars` (gitignored), keeping personal values out of the public repo.

## 013 — Vehicles poller on Lambda, scheduled every minute

- **Decision:** Run the unchanged `ingestion` package on AWS Lambda (`python3.12`, `arm64`, 60 s timeout), triggered by EventBridge Scheduler at `rate(1 minute)` with no flexible window.
- **Decision:** Least privilege with one role per job. The Lambda role may only `s3:PutObject` under `raw/carris/vehicles/*` and write to its own log group. The scheduler role may only invoke this one function, restricted to this account via `aws:SourceAccount`.
- **Decision:** Async retries are disabled in both the schedule and the Lambda. A late retry would fetch the current snapshot, not the missed one, so the next scheduled run is the retry.
- **Decision:** Terraform owns the log group, with 14-day retention (Lambda's default keeps logs forever). The schedule has a `vehicles_schedule_enabled` kill switch to pause ingestion without deleting anything.
- **Rollout:** Deployed with the schedule disabled, verified by a manual invoke and the logs, then enabled.

## 014 — Lambda memory sized from measurement

- **Finding:** At 128 MB, runs peaked at 99–100 MB used (~78%), most of it Python plus boto3. Cold start ~6.7 s; warm runs ~0.85–0.95 s.
- **Decision:** Raise memory to 256 MB for headroom as payloads grow. Lambda CPU scales with memory; the extra cost is negligible at ~43k runs/month.

## 015 — Vehicle payload size depends on the service day (corrects 009)

- **Finding:** Exploration samples (Mon 5 Oct, a Portuguese public holiday; Sat 17 Oct afternoon) returned ~430 vehicles, ~330–350 KB. A regular weekday morning (Mon 26 Oct, 09:00 UTC) returned ~1,220–1,240 vehicles, ~1 MB. All 1,218 vehicles in one sample had a `trip_id`, so the extra records are buses in service, not idle ones.
- **Interpretation:** The earlier samples were most likely reduced (holiday and weekend) service, so 009's volume estimate is roughly 3x low for weekday peaks.
- **Decision:** Keep ingesting everything raw. Replace estimates with measured daily volumes once a week of data exists; storage remains well under $1/month either way.

## 016 — Measured volumes and performance (supersedes the estimates in 009 and 015)

- **Context:** Audited with `scripts/audit_vehicles.py` and CloudWatch Logs Insights on 28 Oct 2026, covering go-live (26 Oct, 09:00 UTC) onwards. Weekday data only so far.
- **Finding, completeness:** 100% of expected runs collected, 0 gaps longer than 90 s. The only anomalies are 2 extra files from manual test invokes.
- **Finding, volume:** The first full day (Tue 27 Oct) was 1,440 files and 79.4 MB gzipped, averaging 55 KB per file, which projects to ~2.4 GB a month. That is about half of 015's estimate: a single peak-hour snapshot (~1 MB raw) overstates the daily average, because night-time snapshots are much smaller. Daily volume follows the service cycle and has to be measured across whole days.
- **Finding, performance at 256 MB:** Average ~0.48 s, p99 ~2.0–2.3 s, worst ~4 s on a warm day (8.9 s on deploy day, including cold starts), against a 60 s timeout. Peak memory was 102 MB (~40%), almost all of it the Python runtime and boto3, so memory barely depends on payload size.
- **Finding, cost:** Average duration roughly halved compared with 128 MB (~0.9 s), consistent with Lambda giving more CPU at more memory, so compute cost (GB-seconds) stayed about the same while headroom doubled.
- **Decision:** Keep 256 MB and the 60 s timeout. Re-run the audit after the first weekend to measure reduced-service volumes.
