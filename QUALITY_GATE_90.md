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

- Functional Completeness: `85`
- Stability & Reliability: `83`
- Test Coverage & Regression Safety: `88`
- Documentation Quality: `78`
- Dependency Governance: `80`
- Release & Packaging Consistency: `84`
- Security Posture: `76`
- Operability & Observability: `79`

## Priority Plan To Reach 90+

1. Documentation quality to 90+
2. Security defaults and safety controls to 90+
3. Dependency governance hardening to 90+
4. Operability/observability improvements to 90+
5. Final multi-run stability verification and score refresh

## Exit Criteria

You may start new feature work only when:

- Every dimension above is scored `>= 90`
- Evidence and gate checks are updated in this file
- Final verification run is recorded
