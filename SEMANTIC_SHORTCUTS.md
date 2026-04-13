# Semantic Shortcut Rules

This file documents the current semantic shortcut routing policy.

## Current Rule (Length-Based)

Use text length after removing spaces:

- `0-5` chars: allow shortcut keyword **contains-match** and execute shortcut directly.
- `6-10` chars: if shortcut keyword matches, show **ambiguity confirmation**:
  - `Execute Shortcut`
  - `Send To AI`
  - `Cancel`
- `11+` chars: do not run shortcut auto-routing; treat as normal conversation and send to AI.

## Scope

This rule is applied to semantic shortcut path in request routing:

- flat menu shortcuts
- flat brain shortcuts

## If You Want To Change The Rule

1. Edit this document first (as product behavior spec).
2. Update implementation in:
   - `robot/routing.py`
3. Run tests:
   - `pytest -q`

## Current Default Thresholds

- direct contains-match max length: `5`
- ambiguity confirmation range: `6-10`
- send-to-AI min length: `11`

