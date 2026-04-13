# Dependency Upgrade Strategy

This project uses a conservative upgrade policy to keep runtime behavior stable.

## Principles

- Prefer reproducible, compatible installs over newest possible versions.
- Upgrade direct dependencies first, then transitive heavy dependencies.
- Do not keep resolver-conflict environments on main branch.
- Every dependency upgrade must pass full test suite.

## Current Compatibility Notes

- `markitdown==0.1.5` depends on `magika~=0.6.1`.
- On Windows, `magika 0.6.3` requires `onnxruntime<=1.20.1`.
- Therefore `magika 0.6.3 + onnxruntime 1.24.x` is not a supported combo.

## Locked Constraints

`constraints.txt` is used during bootstrap to avoid accidental incompatible resolver outcomes.

Current pins:

- `magika==0.6.3` (Windows)
- `onnxruntime==1.20.1` (Windows)
- `mpmath==1.3.0`
- `pdfminer.six==20251230`

## Upgrade Workflow

1. Create a feature branch for upgrade only.
2. Upgrade one dependency family at a time.
3. Run:
   - `pytest -q`
   - representative runtime smoke tests
4. If dependency constraints conflict:
   - keep current stable pins on main
   - document blocker here
5. Merge only when resolver and tests are both green.

## Commands

Outdated check:

```bash
python -m pip list --outdated --format=columns
```

Install with project constraints:

```bash
python -m pip install --no-build-isolation -c constraints.txt -e .
```

## Related Docs

- `README.md`
- `RUNBOOK.md`
- `QUALITY_GATE_90.md`
