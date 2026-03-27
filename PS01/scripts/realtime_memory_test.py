#!/usr/bin/env python3
"""
Launcher wrapper so realtime script can be run directly from PS01 directory.
"""

from pathlib import Path
import runpy
import sys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    target = repo_root / "scripts" / "realtime_memory_test.py"
    if not target.exists():
        print(f"Target script not found: {target}")
        return 1

    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
