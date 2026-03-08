#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import wave


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "tests" / "cases"
MANIFEST_PATH = CASES_DIR / "case_manifest.json"
GENERATED_DIR = REPO_ROOT / "tests" / "_generated"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "measurements"
BUILD_DIR = REPO_ROOT / "build"
TRUE_BYPASS_NULL_THRESHOLD_DBFS = -120.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a narrow set of ProgramEQ measurement renders.")
    parser.add_argument("--plugin", type=pathlib.Path, help="Path to ProgramEQ.vst3")
    parser.add_argument("--sr", type=int, default=48000, help="Sample rate in Hz")
    parser.add_argument("--bs", type=int, default=256, help="Block size in samples")
    parser.add_argument("--group", choices=("smoke", "fr", "bypass", "all"), default="all")
    return parser.parse_args()


def run_command(command: list[str], stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return completed


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def unique_case_names(manifest: dict, group: str) -> list[str]:
    groups = manifest.get("groups", {})
    if group == "all":
        ordered: list[str] = []
        seen: set[str] = set()
        for group_name in ("smoke", "fr", "bypass"):
            for case_name in groups.get(group_name, []):
                if case_name not in seen:
                    ordered.append(case_name)
                    seen.add(case_name)
        return ordered

    return list(groups.get(group, []))


def groups_for_case(manifest: dict, case_name: str) -> list[str]:
    memberships: list[str] = []
    for group_name, case_names in manifest.get("groups", {}).items():
        if case_name in case_names:
            memberships.append(group_name)
    return memberships


def locate_harness() -> pathlib.Path:
    candidates = sorted(BUILD_DIR.rglob("vst3_harness.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("Could not find vst3_harness.exe under build/")
    return candidates[0]


def locate_plugin(plugin_arg: pathlib.Path | None) -> pathlib.Path:
    if plugin_arg is not None:
        plugin_path = plugin_arg.resolve()
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin path does not exist: {plugin_path}")
        return plugin_path

    candidates = sorted((path for path in BUILD_DIR.rglob("*.vst3") if path.is_dir()),
                        key=lambda path: path.stat().st_mtime,
                        reverse=True)
    if not candidates:
        raise FileNotFoundError("Could not find a built .vst3 plugin directory under build/")
    return candidates[0]


def wav_sample_rate(path: pathlib.Path) -> int:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getframerate()


def ensure_impulse(sample_rate: int) -> pathlib.Path:
    impulse_path = GENERATED_DIR / "impulse.wav"
    if impulse_path.exists():
        try:
            if wav_sample_rate(impulse_path) == sample_rate:
                return impulse_path
        except wave.Error:
            pass

    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "generate_stimuli.py"),
        "--outdir",
        str(GENERATED_DIR),
        "--sr",
        str(sample_rate),
        "--overwrite",
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to generate stimuli:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return impulse_path


def parse_metrics(metrics_path: pathlib.Path) -> dict | None:
    if not metrics_path.exists():
        return None
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def run_case(
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    case_name: str,
    case_path: pathlib.Path,
    output_root: pathlib.Path,
    sample_rate: int,
    block_size: int,
    manifest: dict,
) -> dict:
    case_root = output_root / case_name
    render_outdir = case_root / "render"
    analyze_outdir = case_root / "analyze"
    render_outdir.mkdir(parents=True, exist_ok=True)

    render_stdout = case_root / "render.stdout.txt"
    render_stderr = case_root / "render.stderr.txt"
    render_command = [
        str(harness_path),
        "render",
        "--plugin",
        str(plugin_path),
        "--in",
        str(dry_impulse_path),
        "--outdir",
        str(render_outdir),
        "--sr",
        str(sample_rate),
        "--bs",
        str(block_size),
        "--ch",
        "2",
        "--case",
        str(case_path),
    ]
    render_completed = run_command(render_command, render_stdout, render_stderr)
    wet_path = render_outdir / "wet.wav"

    result = {
        "case": case_name,
        "groups": groups_for_case(manifest, case_name),
        "casePath": str(case_path.resolve()),
        "render": {
            "command": render_command,
            "exitCode": render_completed.returncode,
            "stdoutPath": str(render_stdout.resolve()),
            "stderrPath": str(render_stderr.resolve()),
            "outDir": str(render_outdir.resolve()),
            "wetPath": str(wet_path.resolve()),
        },
        "analysis": None,
        "pass": False,
        "message": "",
    }

    if render_completed.returncode != 0:
        result["message"] = "Render failed"
        return result

    if not wet_path.exists():
        result["message"] = "Render succeeded but wet.wav was not created"
        return result

    if case_name == "true_bypass_on":
        analyze_outdir.mkdir(parents=True, exist_ok=True)
        analyze_stdout = case_root / "analyze.stdout.txt"
        analyze_stderr = case_root / "analyze.stderr.txt"
        analyze_command = [
            str(harness_path),
            "analyze",
            "--dry",
            str(dry_impulse_path),
            "--wet",
            str(wet_path),
            "--outdir",
            str(analyze_outdir),
            "--auto-align",
            "--null",
        ]
        analyze_completed = run_command(analyze_command, analyze_stdout, analyze_stderr)
        metrics_path = analyze_outdir / "metrics.json"
        metrics = parse_metrics(metrics_path)
        delta_rms_dbfs = None if metrics is None else metrics.get("deltaRmsDbfs")

        result["analysis"] = {
            "command": analyze_command,
            "exitCode": analyze_completed.returncode,
            "stdoutPath": str(analyze_stdout.resolve()),
            "stderrPath": str(analyze_stderr.resolve()),
            "outDir": str(analyze_outdir.resolve()),
            "metricsPath": str(metrics_path.resolve()),
            "deltaRmsDbfs": delta_rms_dbfs,
            "thresholdDbfs": TRUE_BYPASS_NULL_THRESHOLD_DBFS,
        }

        if analyze_completed.returncode != 0:
            result["message"] = "Analyze failed"
            return result

        if delta_rms_dbfs is None:
            result["message"] = "Analyze succeeded but metrics.json did not contain deltaRmsDbfs"
            return result

        if float(delta_rms_dbfs) > TRUE_BYPASS_NULL_THRESHOLD_DBFS:
            result["message"] = (
                f"True bypass null RMS {float(delta_rms_dbfs):.2f} dBFS exceeded "
                f"{TRUE_BYPASS_NULL_THRESHOLD_DBFS:.2f} dBFS threshold"
            )
            return result

    result["pass"] = True
    result["message"] = "OK"
    return result


def main() -> int:
    args = parse_args()
    if args.sr <= 0:
        raise ValueError("--sr must be positive")
    if args.bs <= 0:
        raise ValueError("--bs must be positive")

    manifest = load_manifest()
    case_names = unique_case_names(manifest, args.group)
    if not case_names:
        raise ValueError(f"No cases found for group '{args.group}'")

    harness_path = locate_harness()
    plugin_path = locate_plugin(args.plugin)
    dry_impulse_path = ensure_impulse(args.sr)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = ARTIFACTS_ROOT / timestamp
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    any_failed = False

    for case_name in case_names:
        case_path = CASES_DIR / f"{case_name}.json"
        if not case_path.exists():
            results.append(
                {
                    "case": case_name,
                    "groups": groups_for_case(manifest, case_name),
                    "casePath": str(case_path.resolve()),
                    "render": None,
                    "analysis": None,
                    "pass": False,
                    "message": "Case file not found",
                }
            )
            any_failed = True
            continue

        result = run_case(
            harness_path=harness_path,
            plugin_path=plugin_path,
            dry_impulse_path=dry_impulse_path,
            case_name=case_name,
            case_path=case_path,
            output_root=output_root,
            sample_rate=args.sr,
            block_size=args.bs,
            manifest=manifest,
        )
        results.append(result)
        any_failed = any_failed or (not result["pass"])
        status_text = "PASS" if result["pass"] else "FAIL"
        print(f"[{status_text}] {case_name}: {result['message']}")

    summary = {
        "version": "1",
        "run": {
            "timestamp": timestamp,
            "group": args.group,
            "sampleRate": args.sr,
            "blockSize": args.bs,
            "channels": 2,
            "pluginPath": str(plugin_path.resolve()),
            "harnessPath": str(harness_path.resolve()),
            "manifestPath": str(MANIFEST_PATH.resolve()),
            "outputRoot": str(output_root.resolve()),
            "dryImpulsePath": str(dry_impulse_path.resolve()),
        },
        "results": results,
        "pass": not any_failed,
    }

    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {summary_path}")

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
