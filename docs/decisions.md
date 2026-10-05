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
