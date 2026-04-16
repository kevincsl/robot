# Shortcut Routing Policy

Semantic shortcut routing is disabled.

## Current Behavior

- Plain text is treated as normal conversation and sent to AI.
- Deterministic behavior only happens with explicit slash commands (for example `/menu`, `/brain`, `/model`) or Telegram button callbacks.
- Control actions also require explicit command form (for example `/stop`, `/reset`, `/run ...`).

## If You Want To Change The Rule

1. Update this document first (as behavior spec).
2. Update implementation in:
   - `robot/routing.py`
3. Run tests:
   - `pytest -q tests/test_routing.py`

## Related Docs

- `README.md`
- `RUNBOOK.md`
- `QUALITY_GATE_90.md`

