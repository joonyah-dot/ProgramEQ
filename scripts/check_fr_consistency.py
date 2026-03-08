from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "measurements"
DEFAULT_CASE_NAME = "fr_pultec_lf_boost_60hz_100pct"
POINT_TOLERANCE_DB = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare quick_fr_check output against latest measurement-runner FR metrics.")
    parser.add_argument("--dry", type=pathlib.Path, default=REPO_ROOT / "tests" / "_generated" / "impulse.wav")
    parser.add_argument("--run-root", type=pathlib.Path, help="Measurement run directory under artifacts/measurements")
    parser.add_argument("--case", dest="case_name", default=DEFAULT_CASE_NAME)
    parser.add_argument("--tolerance-db", type=float, default=POINT_TOLERANCE_DB)
    return parser.parse_args()


def find_latest_run(case_name: str) -> pathlib.Path:
    candidates = []
    for run_root in sorted(ARTIFACTS_ROOT.iterdir(), reverse=True):
        if not run_root.is_dir():
            continue
        metrics_path = run_root / case_name / "fr_metrics.json"
        wet_path = run_root / case_name / "render" / "wet.wav"
        if metrics_path.exists() and wet_path.exists():
            candidates.append(run_root)
    if not candidates:
        raise FileNotFoundError(f"No measurement run found with FR artifacts for case '{case_name}' under {ARTIFACTS_ROOT}")
    return candidates[0]


def run_quick_check(dry_path: pathlib.Path, wet_path: pathlib.Path, out_path: pathlib.Path) -> dict:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "quick_fr_check.py"),
        "--dry",
        str(dry_path),
        "--wet",
        str(wet_path),
        "--out",
        str(out_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "quick_fr_check.py failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(out_path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    run_root = args.run_root.resolve() if args.run_root else find_latest_run(args.case_name)
    dry_path = args.dry.resolve()
    runner_metrics_path = run_root / args.case_name / "fr_metrics.json"
    wet_path = run_root / args.case_name / "render" / "wet.wav"

    if not dry_path.exists():
        raise FileNotFoundError(f"Dry file not found: {dry_path}")
    if not runner_metrics_path.exists():
        raise FileNotFoundError(f"Runner metrics file not found: {runner_metrics_path}")
    if not wet_path.exists():
        raise FileNotFoundError(f"Wet file not found: {wet_path}")

    runner_metrics = json.loads(runner_metrics_path.read_text(encoding="utf-8"))
    compare_dir = run_root / "_consistency_check"
    compare_dir.mkdir(parents=True, exist_ok=True)
    quick_metrics_path = compare_dir / "quick_fr_metrics.json"
    quick_metrics = run_quick_check(dry_path=dry_path, wet_path=wet_path, out_path=quick_metrics_path)

    max_abs_delta = 0.0
    for label, runner_value in runner_metrics["pointsDb"].items():
        quick_value = quick_metrics["pointsDb"][label]
        delta = abs(float(runner_value) - float(quick_value))
        max_abs_delta = max(max_abs_delta, delta)
        print(f"{label}: runner={float(runner_value):.6f} dB, quick={float(quick_value):.6f} dB, delta={delta:.6f} dB")
        if delta > args.tolerance_db:
            print(f"FAIL: {label} delta {delta:.6f} dB exceeded {args.tolerance_db:.6f} dB")
            return 1

    print(f"PASS: max abs delta {max_abs_delta:.6f} dB within {args.tolerance_db:.6f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
