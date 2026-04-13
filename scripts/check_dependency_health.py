from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    constraints = root / "constraints.txt"
    failures: list[str] = []

    if not constraints.exists():
        failures.append("constraints.txt is missing")
    else:
        content = constraints.read_text(encoding="utf-8")
        required_markers = [
            "magika==0.6.3",
            "onnxruntime==1.20.1",
            "mpmath==1.3.0",
            "pdfminer.six==20251230",
        ]
        for marker in required_markers:
            if marker not in content:
                failures.append(f"constraints.txt missing required pin: {marker}")

    result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    if result.returncode != 0:
        failures.append("pip check reported dependency conflicts")
        detail = (result.stdout or "").strip() or (result.stderr or "").strip()
        if detail:
            failures.append(detail)

    if failures:
        print("dependency health check: FAILED")
        for item in failures:
            print(f"- {item}")
        return 1

    print("dependency health check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
