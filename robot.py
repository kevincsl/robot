from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG_DIR = ROOT / "robot"


def _load_robot_package() -> None:
    if "robot" in sys.modules and hasattr(sys.modules["robot"], "__path__"):
        return
    spec = importlib.util.spec_from_file_location(
        "robot",
        PKG_DIR / "__init__.py",
        submodule_search_locations=[str(PKG_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load robot package from {PKG_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["robot"] = module
    spec.loader.exec_module(module)


def main() -> None:
    _load_robot_package()
    from robot.hosted_app import main as hosted_main

    hosted_main()


if __name__ == "__main__":
    main()
