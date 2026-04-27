from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPTS = [
    "microplate_centrifuge_server_smoke.py",
    "plateloc_server_smoke.py",
    "automated_plate_seal_remover_server_smoke.py",
    "automated_thermal_cycler_server_smoke.py",
    "station_server_smoke.py",
    "trolley_arm_server_smoke.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all direct SiLA2 smoke test scripts.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds passed to each smoke test",
    )
    args = parser.parse_args()

    samples_dir = Path(__file__).resolve().parent
    failures: list[str] = []

    for script_name in SCRIPTS:
        script_path = samples_dir / script_name
        print(f"== Running {script_name} ==")
        result = subprocess.run(
            [sys.executable, str(script_path), "--timeout", str(args.timeout)],
            check=False,
        )
        if result.returncode != 0:
            failures.append(script_name)

    if failures:
        print("Smoke test failures:")
        for script_name in failures:
            print(f"- {script_name}")
        return 1

    print("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
