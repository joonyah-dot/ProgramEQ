#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import subprocess
import sys
import wave

import fr_analysis


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "tests" / "cases"
MANIFEST_PATH = CASES_DIR / "case_manifest.json"
GENERATED_DIR = REPO_ROOT / "tests" / "_generated"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "measurements"
BUILD_DIR = REPO_ROOT / "build"
TRUE_BYPASS_NULL_THRESHOLD_DBFS = -120.0
EQ_IN_DIFFERENCE_MIN_DBFS = -120.0
EQ_IN_ON_REFERENCE_CASE = "fr_pultec_lf_boost_60hz_100pct"
FR_MIN_LOW_FREQUENCY_EMPHASIS_DB = 3.0
FR_MONOTONIC_TOLERANCE_DB = 0.5
FR_MIN_LOW_FREQUENCY_ATTENUATION_DB = 2.0
FR_MIN_COMBINED_LOW_FREQUENCY_SHAPE_SPAN_DB = 0.5
FR_MIN_COMBINED_DEVIATION_FROM_SIMPLE_SUM_DB = 0.25


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


def load_case_definition(case_path: pathlib.Path) -> dict:
    return json.loads(case_path.read_text(encoding="utf-8"))


def render_case_to_outdir(
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    case_path: pathlib.Path,
    output_dir: pathlib.Path,
    sample_rate: int,
    block_size: int,
    stdout_path: pathlib.Path,
    stderr_path: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(harness_path),
        "render",
        "--plugin",
        str(plugin_path),
        "--in",
        str(dry_impulse_path),
        "--outdir",
        str(output_dir),
        "--sr",
        str(sample_rate),
        "--bs",
        str(block_size),
        "--ch",
        "2",
        "--case",
        str(case_path),
    ]
    return run_command(command, stdout_path, stderr_path)


def analyze_null(
    harness_path: pathlib.Path,
    dry_path: pathlib.Path,
    wet_path: pathlib.Path,
    output_dir: pathlib.Path,
    stdout_path: pathlib.Path,
    stderr_path: pathlib.Path,
) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, dict | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(harness_path),
        "analyze",
        "--dry",
        str(dry_path),
        "--wet",
        str(wet_path),
        "--outdir",
        str(output_dir),
        "--auto-align",
        "--null",
    ]
    completed = run_command(command, stdout_path, stderr_path)
    metrics_path = output_dir / "metrics.json"
    return completed, metrics_path, parse_metrics(metrics_path)


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
    render_stdout = case_root / "render.stdout.txt"
    render_stderr = case_root / "render.stderr.txt"
    case_definition = load_case_definition(case_path)
    render_completed = render_case_to_outdir(
        harness_path=harness_path,
        plugin_path=plugin_path,
        dry_impulse_path=dry_impulse_path,
        case_path=case_path,
        output_dir=render_outdir,
        sample_rate=sample_rate,
        block_size=block_size,
        stdout_path=render_stdout,
        stderr_path=render_stderr,
    )
    wet_path = render_outdir / "wet.wav"

    result = {
        "case": case_name,
        "groups": groups_for_case(manifest, case_name),
        "casePath": str(case_path.resolve()),
        "caseDefinition": case_definition,
        "render": {
            "command": [
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
            ],
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

    result["pass"] = True
    result["message"] = "OK"
    return result


def evaluate_fr_checks(case_definition: dict, points_db: dict[str, float]) -> dict:
    ordered_labels = [f"{int(frequency_hz)}Hz" for frequency_hz in fr_analysis.CHECK_FREQUENCIES_HZ]
    ordered_values = [float(points_db[label]) for label in ordered_labels]
    params_by_name = case_definition.get("paramsByName", {})
    boost_amount = float(params_by_name.get("pultec.lf_boost_db", 0.0))
    attenuation_amount = float(params_by_name.get("pultec.lf_atten_db", 0.0))
    boost_enabled = boost_amount > 0.0
    attenuation_enabled = attenuation_amount > 0.0

    if attenuation_enabled and not boost_enabled:
        low_frequency_attenuation_db = ordered_values[-1] - ordered_values[0]
        monotonic_increase = all(
            ordered_values[index] <= (ordered_values[index + 1] + FR_MONOTONIC_TOLERANCE_DB)
            for index in range(len(ordered_values) - 1)
        )
        negative_gain = min(ordered_values[:4]) < 0.0
        attenuation_pass = low_frequency_attenuation_db >= FR_MIN_LOW_FREQUENCY_ATTENUATION_DB
        passed = monotonic_increase and negative_gain and attenuation_pass
        return {
            "mode": "attenuation_only",
            "passed": passed,
            "checks": {
                "monotonicIncreaseWithinTolerance": monotonic_increase,
                "lowFrequencyAttenuationDb": low_frequency_attenuation_db,
                "minimumLowFrequencyAttenuationDb": FR_MIN_LOW_FREQUENCY_ATTENUATION_DB,
                "negativeGainAtLfPoints": negative_gain,
                "monotonicToleranceDb": FR_MONOTONIC_TOLERANCE_DB,
            },
        }

    if boost_enabled and attenuation_enabled:
        low_frequency_shape_span_db = abs(ordered_values[0] - ordered_values[-1])
        any_shaping = max(abs(value) for value in ordered_values) >= 0.5
        passed = low_frequency_shape_span_db >= FR_MIN_COMBINED_LOW_FREQUENCY_SHAPE_SPAN_DB and any_shaping
        return {
            "mode": "boost_and_attenuation",
            "passed": passed,
            "checks": {
                "lowFrequencyShapeSpanDb": low_frequency_shape_span_db,
                "minimumLowFrequencyShapeSpanDb": FR_MIN_COMBINED_LOW_FREQUENCY_SHAPE_SPAN_DB,
                "anyShapingAboveHalfDb": any_shaping,
            },
        }

    low_frequency_emphasis_db = ordered_values[0] - ordered_values[-1]
    monotonic_decrease = all(
        ordered_values[index] >= (ordered_values[index + 1] - FR_MONOTONIC_TOLERANCE_DB)
        for index in range(len(ordered_values) - 1)
    )
    positive_gain = max(ordered_values[:4]) > 0.0
    emphasis_pass = low_frequency_emphasis_db >= FR_MIN_LOW_FREQUENCY_EMPHASIS_DB
    passed = monotonic_decrease and positive_gain and emphasis_pass
    return {
        "mode": "boost_only",
        "passed": passed,
        "checks": {
            "monotonicDecreaseWithinTolerance": monotonic_decrease,
            "lowFrequencyEmphasisDb": low_frequency_emphasis_db,
            "minimumLowFrequencyEmphasisDb": FR_MIN_LOW_FREQUENCY_EMPHASIS_DB,
            "positiveGainAtLfPoints": positive_gain,
            "monotonicToleranceDb": FR_MONOTONIC_TOLERANCE_DB,
        },
    }


def format_fr_failure(provisional: dict) -> str:
    mode = provisional.get("mode", "unknown")
    checks = provisional.get("checks", {})

    if mode == "attenuation_only":
        return (
            "FR provisional checks failed: "
            f"LF attenuation {checks.get('lowFrequencyAttenuationDb', 0.0):.2f} dB, "
            f"monotonic={checks.get('monotonicIncreaseWithinTolerance')}, "
            f"negativeGain={checks.get('negativeGainAtLfPoints')}"
        )

    if mode == "boost_and_attenuation":
        return (
            "FR provisional checks failed: "
            f"shape span {checks.get('lowFrequencyShapeSpanDb', 0.0):.2f} dB, "
            f"anyShaping={checks.get('anyShapingAboveHalfDb')}"
        )

    return (
        "FR provisional checks failed: "
        f"LF emphasis {checks.get('lowFrequencyEmphasisDb', 0.0):.2f} dB, "
        f"monotonic={checks.get('monotonicDecreaseWithinTolerance')}, "
        f"positiveGain={checks.get('positiveGainAtLfPoints')}"
    )


def build_reference_case_definition(case_definition: dict, boost_amount: float, attenuation_amount: float) -> dict:
    reference_case = copy.deepcopy(case_definition)
    params_by_name = reference_case.setdefault("paramsByName", {})
    params_by_name["pultec.lf_boost_db"] = boost_amount
    params_by_name["pultec.lf_atten_db"] = attenuation_amount
    return reference_case


def reference_cache_key(case_definition: dict) -> tuple[float, float, float]:
    params_by_name = case_definition.get("paramsByName", {})
    return (
        float(params_by_name.get("pultec.lf_freq_hz", 0.0)),
        float(params_by_name.get("pultec.lf_boost_db", 0.0)),
        float(params_by_name.get("pultec.lf_atten_db", 0.0)),
    )


def render_reference_fr_case(
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    output_root: pathlib.Path,
    sample_rate: int,
    block_size: int,
    case_definition: dict,
    reference_label: str,
    reference_cache: dict[tuple[float, float, float], dict],
) -> dict:
    cache_key = reference_cache_key(case_definition)
    if cache_key in reference_cache:
        return reference_cache[cache_key]

    freq_norm, boost_norm, atten_norm = cache_key
    reference_name = (
        f"lf_freq_{freq_norm:.7f}__boost_{boost_norm:.7f}__atten_{atten_norm:.7f}__{reference_label}"
        .replace(".", "p")
    )
    reference_root = output_root / "_references" / reference_name
    reference_root.mkdir(parents=True, exist_ok=True)

    case_path = reference_root / "case.json"
    case_path.write_text(json.dumps(case_definition, indent=2), encoding="utf-8")
    render_stdout = reference_root / "render.stdout.txt"
    render_stderr = reference_root / "render.stderr.txt"
    render_completed = render_case_to_outdir(
        harness_path=harness_path,
        plugin_path=plugin_path,
        dry_impulse_path=dry_impulse_path,
        case_path=case_path,
        output_dir=reference_root / "render",
        sample_rate=sample_rate,
        block_size=block_size,
        stdout_path=render_stdout,
        stderr_path=render_stderr,
    )
    wet_path = reference_root / "render" / "wet.wav"
    if render_completed.returncode != 0 or not wet_path.exists():
        raise RuntimeError(f"Reference render failed for {reference_name}")

    analysis = fr_analysis.analyze_frequency_response_files(dry_impulse_path, wet_path)
    metrics_path = reference_root / "fr_metrics.json"
    fr_analysis.write_metrics_json(metrics_path, analysis)
    reference_info = {
        "label": reference_label,
        "casePath": str(case_path.resolve()),
        "metricsPath": str(metrics_path.resolve()),
        "wetPath": str(wet_path.resolve()),
        "pointsDb": {label: float(value) for label, value in analysis["pointsDb"].items()},
    }
    reference_cache[cache_key] = reference_info
    return reference_info


def build_combined_interaction_comparison(
    case_name: str,
    case_root: pathlib.Path,
    combined_points: dict[str, float],
    boost_reference: dict,
    attenuation_reference: dict,
) -> dict:
    labels = [f"{int(frequency_hz)}Hz" for frequency_hz in fr_analysis.CHECK_FREQUENCIES_HZ]
    additive_points = {
        label: float(boost_reference["pointsDb"][label]) + float(attenuation_reference["pointsDb"][label])
        for label in labels
    }
    deviation_points = {
        label: float(combined_points[label]) - float(additive_points[label])
        for label in labels
    }
    max_deviation_label = max(labels, key=lambda label: abs(deviation_points[label]))
    peak_label = max(labels, key=lambda label: combined_points[label])
    max_abs_deviation_db = abs(deviation_points[max_deviation_label])
    not_simple_cancellation = max_abs_deviation_db >= FR_MIN_COMBINED_DEVIATION_FROM_SIMPLE_SUM_DB
    note = (
        f"Combined peak at {peak_label}; deviation from simple dB-sum is {max_abs_deviation_db:.2f} dB "
        f"at {max_deviation_label}, which indicates retained boost with tightening below the peak."
        if not_simple_cancellation
        else (
            f"Combined peak at {peak_label}; deviation from simple dB-sum is only {max_abs_deviation_db:.2f} dB "
            f"at {max_deviation_label}."
        )
    )
    comparison = {
        "case": case_name,
        "boostOnly": {
            "metricsPath": boost_reference["metricsPath"],
            "pointsDb": boost_reference["pointsDb"],
        },
        "attenOnly": {
            "metricsPath": attenuation_reference["metricsPath"],
            "pointsDb": attenuation_reference["pointsDb"],
        },
        "combined": {
            "pointsDb": {label: float(value) for label, value in combined_points.items()},
        },
        "simpleAdditiveApproximationDb": additive_points,
        "deviationFromSimpleAdditiveDb": deviation_points,
        "maxAbsDeviationDb": max_abs_deviation_db,
        "maxAbsDeviationLabel": max_deviation_label,
        "notSimpleCancellation": not_simple_cancellation,
        "minimumDeviationDb": FR_MIN_COMBINED_DEVIATION_FROM_SIMPLE_SUM_DB,
        "note": note,
    }
    comparison_path = case_root / "interaction_comparison.json"
    comparison_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    comparison["comparisonPath"] = str(comparison_path.resolve())
    return comparison


def render_reference_case(
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    output_root: pathlib.Path,
    sample_rate: int,
    block_size: int,
) -> dict:
    case_path = CASES_DIR / f"{EQ_IN_ON_REFERENCE_CASE}.json"
    if not case_path.exists():
        raise FileNotFoundError(f"Reference case file not found: {case_path}")

    reference_root = output_root / "_references" / EQ_IN_ON_REFERENCE_CASE
    stdout_path = reference_root / "render.stdout.txt"
    stderr_path = reference_root / "render.stderr.txt"
    render_completed = render_case_to_outdir(
        harness_path=harness_path,
        plugin_path=plugin_path,
        dry_impulse_path=dry_impulse_path,
        case_path=case_path,
        output_dir=reference_root / "render",
        sample_rate=sample_rate,
        block_size=block_size,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    wet_path = reference_root / "render" / "wet.wav"
    return {
        "case": EQ_IN_ON_REFERENCE_CASE,
        "casePath": str(case_path.resolve()),
        "renderExitCode": render_completed.returncode,
        "stdoutPath": str(stdout_path.resolve()),
        "stderrPath": str(stderr_path.resolve()),
        "outDir": str((reference_root / "render").resolve()),
        "wetPath": str(wet_path.resolve()),
        "exists": wet_path.exists(),
    }


def apply_bypass_analysis(
    results_by_case: dict[str, dict],
    harness_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    output_root: pathlib.Path,
    plugin_path: pathlib.Path,
    sample_rate: int,
    block_size: int,
) -> dict | None:
    true_bypass_result = results_by_case.get("true_bypass_on")
    eq_in_off_result = results_by_case.get("eq_in_off_lf_boost_set")

    if true_bypass_result is None and eq_in_off_result is None:
        return None

    bypass_metrics: dict[str, dict] = {}

    if true_bypass_result is not None and true_bypass_result.get("render", {}).get("exitCode") == 0:
        case_root = output_root / "true_bypass_on"
        analyze_stdout = case_root / "analyze.stdout.txt"
        analyze_stderr = case_root / "analyze.stderr.txt"
        analyze_outdir = case_root / "analyze"
        wet_path = pathlib.Path(true_bypass_result["render"]["wetPath"])
        analyze_completed, metrics_path, metrics = analyze_null(
            harness_path=harness_path,
            dry_path=dry_impulse_path,
            wet_path=wet_path,
            output_dir=analyze_outdir,
            stdout_path=analyze_stdout,
            stderr_path=analyze_stderr,
        )
        delta_rms_dbfs = None if metrics is None else metrics.get("deltaRmsDbfs")
        true_bypass_result["analysis"] = {
            "kind": "true_bypass_null",
            "command": [
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
            ],
            "exitCode": analyze_completed.returncode,
            "stdoutPath": str(analyze_stdout.resolve()),
            "stderrPath": str(analyze_stderr.resolve()),
            "outDir": str(analyze_outdir.resolve()),
            "metricsPath": str(metrics_path.resolve()),
            "deltaRmsDbfs": delta_rms_dbfs,
            "thresholdDbfs": TRUE_BYPASS_NULL_THRESHOLD_DBFS,
        }

        true_bypass_pass = (
            analyze_completed.returncode == 0
            and delta_rms_dbfs is not None
            and float(delta_rms_dbfs) <= TRUE_BYPASS_NULL_THRESHOLD_DBFS
        )
        true_bypass_result["pass"] = true_bypass_pass
        true_bypass_result["message"] = (
            "OK"
            if true_bypass_pass
            else (
                "Analyze failed"
                if analyze_completed.returncode != 0
                else "Analyze succeeded but metrics.json did not contain deltaRmsDbfs"
                if delta_rms_dbfs is None
                else (
                    f"True bypass null RMS {float(delta_rms_dbfs):.2f} dBFS exceeded "
                    f"{TRUE_BYPASS_NULL_THRESHOLD_DBFS:.2f} dBFS threshold"
                )
            )
        )
        bypass_metrics["trueBypassOn"] = {
            "case": "true_bypass_on",
            "deltaRmsDbfs": delta_rms_dbfs,
            "thresholdDbfs": TRUE_BYPASS_NULL_THRESHOLD_DBFS,
            "pass": true_bypass_pass,
            "metricsPath": str(metrics_path.resolve()),
        }

    if eq_in_off_result is not None and eq_in_off_result.get("render", {}).get("exitCode") == 0:
        reference_result = results_by_case.get(EQ_IN_ON_REFERENCE_CASE)
        reference_info: dict
        if reference_result is not None and reference_result.get("render", {}).get("exitCode") == 0:
            reference_info = {
                "case": EQ_IN_ON_REFERENCE_CASE,
                "casePath": reference_result["casePath"],
                "renderExitCode": reference_result["render"]["exitCode"],
                "stdoutPath": reference_result["render"]["stdoutPath"],
                "stderrPath": reference_result["render"]["stderrPath"],
                "outDir": reference_result["render"]["outDir"],
                "wetPath": reference_result["render"]["wetPath"],
                "exists": pathlib.Path(reference_result["render"]["wetPath"]).exists(),
            }
        else:
            reference_info = render_reference_case(
                harness_path=harness_path,
                plugin_path=plugin_path,
                dry_impulse_path=dry_impulse_path,
                output_root=output_root,
                sample_rate=sample_rate,
                block_size=block_size,
            )

        analyze_root = output_root / "eq_in_off_lf_boost_set" / "analyze"
        analyze_stdout = output_root / "eq_in_off_lf_boost_set" / "analyze.stdout.txt"
        analyze_stderr = output_root / "eq_in_off_lf_boost_set" / "analyze.stderr.txt"

        delta_rms_dbfs = None
        analyze_exit_code = 1
        metrics_path = analyze_root / "metrics.json"

        if reference_info["renderExitCode"] == 0 and reference_info["exists"]:
            analyze_completed, metrics_path, metrics = analyze_null(
                harness_path=harness_path,
                dry_path=pathlib.Path(eq_in_off_result["render"]["wetPath"]),
                wet_path=pathlib.Path(reference_info["wetPath"]),
                output_dir=analyze_root,
                stdout_path=analyze_stdout,
                stderr_path=analyze_stderr,
            )
            analyze_exit_code = analyze_completed.returncode
            delta_rms_dbfs = None if metrics is None else metrics.get("deltaRmsDbfs")
        else:
            analyze_completed = None

        eq_in_off_result["analysis"] = {
            "kind": "eq_in_shaping_difference",
            "compareCase": EQ_IN_ON_REFERENCE_CASE,
            "compareCasePath": reference_info["casePath"],
            "compareWetPath": reference_info["wetPath"],
            "compareRenderExitCode": reference_info["renderExitCode"],
            "command": None if analyze_completed is None else [
                str(harness_path),
                "analyze",
                "--dry",
                eq_in_off_result["render"]["wetPath"],
                "--wet",
                reference_info["wetPath"],
                "--outdir",
                str(analyze_root),
                "--auto-align",
                "--null",
            ],
            "exitCode": analyze_exit_code,
            "stdoutPath": str(analyze_stdout.resolve()),
            "stderrPath": str(analyze_stderr.resolve()),
            "outDir": str(analyze_root.resolve()),
            "metricsPath": str(metrics_path.resolve()),
            "deltaRmsDbfs": delta_rms_dbfs,
            "minimumDifferenceDbfs": EQ_IN_DIFFERENCE_MIN_DBFS,
        }

        eq_in_pass = (
            reference_info["renderExitCode"] == 0
            and reference_info["exists"]
            and analyze_completed is not None
            and analyze_exit_code == 0
            and delta_rms_dbfs is not None
            and float(delta_rms_dbfs) > EQ_IN_DIFFERENCE_MIN_DBFS
        )
        eq_in_off_result["pass"] = eq_in_pass
        eq_in_off_result["message"] = (
            "OK"
            if eq_in_pass
            else (
                f"Reference render failed for {EQ_IN_ON_REFERENCE_CASE}"
                if reference_info["renderExitCode"] != 0 or not reference_info["exists"]
                else "Analyze failed"
                if analyze_completed is not None and analyze_exit_code != 0
                else "Analyze succeeded but metrics.json did not contain deltaRmsDbfs"
                if delta_rms_dbfs is None
                else (
                    f"EQ IN on/off difference {float(delta_rms_dbfs):.2f} dBFS was not greater than "
                    f"{EQ_IN_DIFFERENCE_MIN_DBFS:.2f} dBFS"
                )
            )
        )
        bypass_metrics["eqInOffLfBoostSet"] = {
            "case": "eq_in_off_lf_boost_set",
            "referenceCase": EQ_IN_ON_REFERENCE_CASE,
            "deltaRmsDbfs": delta_rms_dbfs,
            "minimumDifferenceDbfs": EQ_IN_DIFFERENCE_MIN_DBFS,
            "pass": eq_in_pass,
            "metricsPath": str(metrics_path.resolve()),
            "referenceRender": reference_info,
        }

    bypass_metrics_path = output_root / "bypass_metrics.json"
    bypass_metrics_path.write_text(json.dumps(bypass_metrics, indent=2), encoding="utf-8")
    return {
        "metricsPath": str(bypass_metrics_path.resolve()),
        "results": bypass_metrics,
    }


def apply_fr_analysis(
    results_by_case: dict[str, dict],
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    output_root: pathlib.Path,
    sample_rate: int,
    block_size: int,
) -> dict | None:
    fr_results = {
        case_name: result
        for case_name, result in results_by_case.items()
        if "fr" in result.get("groups", [])
    }
    if not fr_results:
        return None

    metrics_index: dict[str, dict] = {}
    failed_cases: list[str] = []
    reference_cache: dict[tuple[float, float, float], dict] = {}

    for case_name, result in fr_results.items():
        if result.get("render", {}).get("exitCode") != 0:
            metrics_index[case_name] = {
                "case": case_name,
                "pass": False,
                "error": "Render failed",
            }
            failed_cases.append(case_name)
            continue

        wet_path = pathlib.Path(result["render"]["wetPath"])
        if not wet_path.exists():
            result["pass"] = False
            result["message"] = "Render succeeded but wet.wav was not created"
            metrics_index[case_name] = {
                "case": case_name,
                "pass": False,
                "error": result["message"],
            }
            failed_cases.append(case_name)
            continue

        case_root = output_root / case_name
        metrics_path = case_root / "fr_metrics.json"
        curve_path = case_root / "fr_curve.csv"
        plot_path = case_root / "fr_plot.png"

        try:
            analysis = fr_analysis.analyze_frequency_response_files(
                dry_impulse_path,
                wet_path,
            )
            fr_analysis.write_metrics_json(metrics_path, analysis)
            fr_analysis.write_curve_csv(curve_path, analysis["frequenciesHz"], analysis["magnitudeDb"])
            fr_analysis.save_plot(plot_path, analysis["frequenciesHz"], analysis["magnitudeDb"])
            provisional = evaluate_fr_checks(result["caseDefinition"], analysis["pointsDb"])

            result["analysis"] = {
                "kind": "frequency_response",
                "sampleRate": int(analysis["sampleRate"]),
                "shiftSamples": int(analysis["shiftSamples"]),
                "pointsDb": {label: float(value) for label, value in analysis["pointsDb"].items()},
                "metricsPath": str(metrics_path.resolve()),
                "curveCsvPath": str(curve_path.resolve()),
                "plotPath": str(plot_path.resolve()),
                "provisional": provisional,
            }
            params_by_name = result["caseDefinition"].get("paramsByName", {})
            boost_amount = float(params_by_name.get("pultec.lf_boost_db", 0.0))
            attenuation_amount = float(params_by_name.get("pultec.lf_atten_db", 0.0))
            if boost_amount > 0.0 and attenuation_amount > 0.0:
                boost_reference = render_reference_fr_case(
                    harness_path=harness_path,
                    plugin_path=plugin_path,
                    dry_impulse_path=dry_impulse_path,
                    output_root=output_root,
                    sample_rate=sample_rate,
                    block_size=block_size,
                    case_definition=build_reference_case_definition(result["caseDefinition"], boost_amount, 0.0),
                    reference_label="boost_only",
                    reference_cache=reference_cache,
                )
                attenuation_reference = render_reference_fr_case(
                    harness_path=harness_path,
                    plugin_path=plugin_path,
                    dry_impulse_path=dry_impulse_path,
                    output_root=output_root,
                    sample_rate=sample_rate,
                    block_size=block_size,
                    case_definition=build_reference_case_definition(result["caseDefinition"], 0.0, attenuation_amount),
                    reference_label="atten_only",
                    reference_cache=reference_cache,
                )
                interaction_comparison = build_combined_interaction_comparison(
                    case_name=case_name,
                    case_root=case_root,
                    combined_points=result["analysis"]["pointsDb"],
                    boost_reference=boost_reference,
                    attenuation_reference=attenuation_reference,
                )
                result["analysis"]["interactionComparison"] = interaction_comparison

            result["pass"] = bool(provisional["passed"])
            if "interactionComparison" in result["analysis"]:
                result["pass"] = result["pass"] and bool(result["analysis"]["interactionComparison"]["notSimpleCancellation"])
            result["message"] = (
                "OK"
                if result["pass"]
                else format_fr_failure(provisional)
            )
            metrics_index[case_name] = {
                "case": case_name,
                "metricsPath": str(metrics_path.resolve()),
                "curveCsvPath": str(curve_path.resolve()),
                "plotPath": str(plot_path.resolve()),
                "pointsDb": result["analysis"]["pointsDb"],
                "shiftSamples": result["analysis"]["shiftSamples"],
                "interactionComparisonPath": None
                if "interactionComparison" not in result["analysis"]
                else result["analysis"]["interactionComparison"]["comparisonPath"],
                "pass": result["pass"],
            }
            if not result["pass"]:
                failed_cases.append(case_name)
        except Exception as exc:
            result["analysis"] = {
                "kind": "frequency_response",
                "error": str(exc),
                "metricsPath": str(metrics_path.resolve()),
                "curveCsvPath": str(curve_path.resolve()),
                "plotPath": str(plot_path.resolve()),
            }
            result["pass"] = False
            result["message"] = f"FR analysis failed: {exc}"
            failed_cases.append(case_name)

    return {
        "results": metrics_index,
        "failedCases": failed_cases,
    }


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
    results_by_case: dict[str, dict] = {}
    any_failed = False

    for case_name in case_names:
        case_path = CASES_DIR / f"{case_name}.json"
        if not case_path.exists():
            missing_result = {
                "case": case_name,
                "groups": groups_for_case(manifest, case_name),
                "casePath": str(case_path.resolve()),
                "render": None,
                "analysis": None,
                "pass": False,
                "message": "Case file not found",
            }
            results.append(missing_result)
            results_by_case[case_name] = missing_result
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
        results_by_case[case_name] = result

    bypass_summary = apply_bypass_analysis(
        results_by_case=results_by_case,
        harness_path=harness_path,
        dry_impulse_path=dry_impulse_path,
        output_root=output_root,
        plugin_path=plugin_path,
        sample_rate=args.sr,
        block_size=args.bs,
    )
    fr_summary = apply_fr_analysis(
        results_by_case=results_by_case,
        harness_path=harness_path,
        plugin_path=plugin_path,
        dry_impulse_path=dry_impulse_path,
        output_root=output_root,
        sample_rate=args.sr,
        block_size=args.bs,
    )

    if bypass_summary is not None:
        print(f"Wrote: {bypass_summary['metricsPath']}")

    if fr_summary is not None:
        for case_name, fr_result in fr_summary["results"].items():
            print(f"Wrote: {fr_result['metricsPath']}")

    any_failed = any((not result["pass"]) for result in results)
    for result in results:
        status_text = "PASS" if result["pass"] else "FAIL"
        print(f"[{status_text}] {result['case']}: {result['message']}")

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
        "bypass": bypass_summary,
        "fr": fr_summary,
        "results": results,
        "pass": not any_failed,
    }

    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {summary_path}")

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
