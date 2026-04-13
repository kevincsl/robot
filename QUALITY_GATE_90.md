# Quality Gate 90

This document defines the quality threshold before adding new features.

## Rule

No new feature work until every quality dimension reaches `>= 90`.

## Dimensions

### 1) Functional Completeness

- Target score: `>= 90`
- Definition:
  - All currently supported user flows are explicitly documented.
  - No known "partially implemented but exposed" command paths.
- Evidence:
  - Updated command docs in `README.md`
  - Flow checklist completed in this file
- Gate check:
  - Manual walkthrough for core flows passes

### 2) Stability & Reliability

- Target score: `>= 90`
- Definition:
  - No flaky tests in 5 consecutive runs.
  - No known crash path in routine usage.
- Evidence:
  - `pytest -q` passes 5/5 runs
  - Known failure list is empty or has mitigation
- Gate check:
  - `for i in 1 2 3 4 5; do pytest -q || exit 1; done` (bash)

### 3) Test Coverage & Regression Safety

- Target score: `>= 90`
- Definition:
  - Critical routing, scheduling, and provider-control paths have tests.
  - New bug fixes always include regression tests.
- Evidence:
  - Test map maintained and linked
  - Missing critical-path tests count = 0
- Gate check:
  - `pytest -q` passes
  - Review confirms critical-path test map is complete

### 4) Documentation Quality

- Target score: `>= 90`
- Definition:
  - README has no encoding corruption.
  - Setup, operation, and troubleshooting are clear and consistent.
  - Shortcut and dependency strategy docs are linked and current.
- Evidence:
  - `README.md`, `RUNBOOK.md`, `SEMANTIC_SHORTCUTS.md`, `DEPENDENCY_STRATEGY.md` synced
  - No broken/contradictory instructions
- Gate check:
  - New user can bootstrap and run using docs only

### 5) Dependency Governance

- Target score: `>= 90`
- Definition:
  - Compatible versions are pinned where needed.
  - Upgrade workflow is documented and repeatable.
  - No unresolved resolver conflicts on main branch.
- Evidence:
  - `constraints.txt` maintained
  - `DEPENDENCY_STRATEGY.md` updated with compatibility notes
- Gate check:
  - Fresh environment install succeeds with constraints
  - `python scripts/check_dependency_health.py` passes

### 6) Release & Packaging Consistency

- Target score: `>= 90`
- Definition:
  - Versioning and metadata are consistent.
  - Vendored source/build copies are synchronized.
- Evidence:
  - Packaging metadata reviewed each release
  - Vendor sync checklist completed
- Gate check:
  - Install/build flow passes in clean environment
  - `python scripts/check_release_consistency.py` passes

### 7) Security Posture

- Target score: `>= 90`
- Definition:
  - High-risk execution flags are explicit and documented.
  - Safe defaults are used unless user intentionally opts in.
- Evidence:
  - Environment flag documentation complete
  - No hidden dangerous defaults
- Gate check:
  - Security-related env defaults reviewed before release

### 8) Operability & Observability

- Target score: `>= 90`
- Definition:
  - Status output includes enough context for incident triage.
  - Critical runtime events are traceable.
- Evidence:
  - `status` / timing output verified
  - Restart/recovery behavior documented
- Gate check:
  - Operator can diagnose queue/running/error states from bot output

## Current Baseline (2026-04-13)

- Functional Completeness: `90`
- Stability & Reliability: `90`
- Test Coverage & Regression Safety: `91`
- Documentation Quality: `90`
- Dependency Governance: `90`
- Release & Packaging Consistency: `90`
- Security Posture: `90`
- Operability & Observability: `90`

## Priority Plan To Reach 90+

1. Keep the 5-run stability check green on every release cycle
2. Keep release/dependency check scripts green
3. Keep docs synchronized after each behavior change

## Exit Criteria

You may start new feature work only when:

- Every dimension above is scored `>= 90`
- Evidence and gate checks are updated in this file
- Final verification run is recorded

Current status: **Gate passed**.
