# Google Calendar x Robot Schedule Sync Plan

## Goal

Implement two-way sync between Robot schedule data and Google Calendar with clear conflict handling and safe incremental rollout.

## Scope (v1)

- Sync one Google calendar (default: `primary`) with one Robot schedule namespace.
- Sync event fields:
  - title
  - start/end datetime
  - description
  - location
  - updated timestamp
- Support:
  - create
  - update
  - delete (soft-delete strategy first)

## Out of Scope (v1)

- Multi-calendar routing rules
- Recurring event exception editing
- Multi-user permission model

## Data Model

- Add a mapping table/file:
  - `robot_event_id`
  - `google_event_id`
  - `last_synced_at`
  - `source_of_truth` (`robot` / `google`)
  - `sync_status` (`ok` / `conflict` / `deleted`)
- Add metadata tag in Google event `extendedProperties.private`:
  - `robot_event_id`
  - `robot_sync_version`

## Sync Direction Strategy

1. v1.0: Robot -> Google (one-way bootstrap)
2. v1.1: Google -> Robot pull sync (controlled)
3. v1.2: Two-way sync with conflict policy

## Conflict Policy (v1.2)

- Default policy: last-write-wins by `updated_at`.
- If timestamps are too close (e.g. <= 30s), mark as `conflict` and do not auto-merge.
- Emit conflict log + Telegram notification for manual resolution.

## Sync Trigger

- Manual command:
  - `/schedule sync`
- Optional periodic job:
  - every 5 minutes (configurable)
- Startup reconciliation:
  - dry-run mode first, apply mode after verification

## Reliability & Safety

- Dry-run mode (`ROBOT_CAL_SYNC_DRY_RUN=true`)
- Idempotent upsert behavior
- Retry with backoff on Google API transient failures
- Rate-limit outgoing writes to avoid quota spikes
- Audit log for each sync action

## Config

- `GOOGLE_CREDENTIALS_PATH`
- `GOOGLE_TOKEN_PATH`
- `GOOGLE_CALENDAR_ID` (default `primary`)
- `ROBOT_CAL_SYNC_ENABLED`
- `ROBOT_CAL_SYNC_DIRECTION` (`robot_to_google`, `google_to_robot`, `bidirectional`)
- `ROBOT_CAL_SYNC_INTERVAL_SEC`
- `ROBOT_CAL_SYNC_DRY_RUN`

## Milestones

1. M1: Infra + one-way push
   - Add config
   - Add Google client wrapper
   - Add mapping persistence
   - Add `/schedule sync` command (robot -> google)
2. M2: Pull sync + reconciliation
   - Implement google -> robot importer
   - Add dedupe and deleted event handling
3. M3: Bidirectional + conflict handling
   - Enable last-write-wins
   - Add conflict queue + notification
4. M4: Hardening
   - Integration tests
   - Observability metrics
   - Rollout checklist

## Testing Plan

- Unit tests:
  - mapper
  - conflict resolver
  - payload converter
- Integration tests:
  - create/update/delete round-trip
  - dry-run correctness
  - retry/idempotency behavior

## Rollout Plan

1. Enable in dry-run on staging account
2. Compare 3 days of logs (expected vs actual changes)
3. Enable write mode for one calendar
4. Expand to normal operation

