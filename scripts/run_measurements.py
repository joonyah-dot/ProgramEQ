#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import pathlib
import subprocess
import sys
import wave

import fr_analysis
import numpy as np


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
HF_BOOST_FREQUENCY_CHOICES_HZ = [3000.0, 4000.0, 5000.0, 8000.0, 10000.0, 12000.0, 16000.0]
HF_ATTENUATION_SELECTOR_CHOICES_HZ = [5000.0, 10000.0, 20000.0]
HF_MIN_PEAK_GAIN_DB = 3.0
HF_PEAK_TRACKING_TOLERANCE_OCTAVES = 0.35
HF_REFERENCE_SAMPLE_HZ = 1000.0
HF_PLOT_MIN_HZ = 500.0
HF_PLOT_MAX_HZ = 22000.0
HF_WIDTH_DROP_DB = 3.0
HF_BANDWIDTH_LABEL_VALUES = {
    "sharp": 0.0,
    "mid": 0.5,
    "broad": 1.0,
}
HF_BANDWIDTH_VALUE_TOLERANCE = 1.0e-4
HF_BANDWIDTH_ORDER_MARGIN_OCTAVES = 0.02
HF_ATTENUATION_MIN_20K_DB = 2.0
HF_ATTENUATION_MONOTONIC_TOLERANCE_DB = 0.75
HF_ATTENUATION_DISTINCT_MARGIN_DB = 0.5
HF_COMBINED_MIN_DEVIATION_FROM_ADDITIVE_DB = 0.25


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


def hf_frequency_selection_to_hz(normalized_value: float) -> float:
    clamped = max(0.0, min(1.0, float(normalized_value)))
    index = int(round(clamped * float(len(HF_BOOST_FREQUENCY_CHOICES_HZ) - 1)))
    return HF_BOOST_FREQUENCY_CHOICES_HZ[index]


def hf_attenuation_selection_to_hz(normalized_value: float) -> float:
    clamped = max(0.0, min(1.0, float(normalized_value)))
    index = int(round(clamped * float(len(HF_ATTENUATION_SELECTOR_CHOICES_HZ) - 1)))
    return HF_ATTENUATION_SELECTOR_CHOICES_HZ[index]


def hf_bandwidth_value_to_label(normalized_value: float) -> str | None:
    for label, reference_value in HF_BANDWIDTH_LABEL_VALUES.items():
        if abs(float(normalized_value) - reference_value) <= HF_BANDWIDTH_VALUE_TOLERANCE:
            return label
    return None


def write_fr_metrics_json(metrics_path: pathlib.Path, analysis: dict, provisional: dict) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_payload = fr_analysis.serialise_metrics(analysis)
    metrics_payload["provisional"] = provisional
    metrics_path.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")


def evaluate_fr_checks(case_definition: dict, analysis: dict) -> dict:
    points_db = analysis["pointsDb"]
    ordered_labels = [f"{int(frequency_hz)}Hz" for frequency_hz in fr_analysis.CHECK_FREQUENCIES_HZ]
    ordered_values = [float(points_db[label]) for label in ordered_labels]
    params_by_name = case_definition.get("paramsByName", {})
    boost_amount = float(params_by_name.get("pultec.lf_boost_db", 0.0))
    attenuation_amount = float(params_by_name.get("pultec.lf_atten_db", 0.0))
    hf_boost_amount = float(params_by_name.get("pultec.hf_boost_db", 0.0))
    hf_attenuation_amount = float(params_by_name.get("pultec.hf_atten_db", 0.0))
    hf_bandwidth_normalized = float(params_by_name.get("pultec.hf_bandwidth", 0.5))
    boost_enabled = boost_amount > 0.0
    attenuation_enabled = attenuation_amount > 0.0
    hf_boost_enabled = hf_boost_amount > 0.0
    hf_attenuation_enabled = hf_attenuation_amount > 0.0

    if hf_boost_enabled and hf_attenuation_enabled and not boost_enabled and not attenuation_enabled:
        target_frequency_hz = hf_frequency_selection_to_hz(float(params_by_name.get("pultec.hf_boost_freq_khz", 0.0)))
        selector_frequency_hz = hf_attenuation_selection_to_hz(float(params_by_name.get("pultec.hf_atten_sel_khz", 0.0)))
        peak = fr_analysis.find_peak_in_band(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            max(HF_PLOT_MIN_HZ, target_frequency_hz * 0.5),
            min(HF_PLOT_MAX_HZ, target_frequency_hz * 1.75),
        )
        sample_points = fr_analysis.sample_points_at_frequencies(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            [HF_REFERENCE_SAMPLE_HZ, target_frequency_hz, selector_frequency_hz, 20000.0],
        )
        reference_magnitude_db = float(sample_points[fr_analysis.format_frequency_label(HF_REFERENCE_SAMPLE_HZ)])
        peak_prominence_db = float(peak["magnitudeDb"]) - reference_magnitude_db
        attenuation_at_20k_db = reference_magnitude_db - float(sample_points["20000Hz"])
        tracking_error_octaves = abs(math.log2(peak["frequencyHz"] / target_frequency_hz))
        passed = (
            peak_prominence_db >= 1.0
            and attenuation_at_20k_db >= 1.0
            and tracking_error_octaves <= HF_PEAK_TRACKING_TOLERANCE_OCTAVES
        )
        return {
            "mode": "hf_boost_and_attenuation",
            "passed": passed,
            "checks": {
                "targetFrequencyHz": target_frequency_hz,
                "selectorFrequencyHz": selector_frequency_hz,
                "peakFrequencyHz": float(peak["frequencyHz"]),
                "peakMagnitudeDb": float(peak["magnitudeDb"]),
                "peakProminenceDb": peak_prominence_db,
                "attenuationAt20kDb": attenuation_at_20k_db,
                "trackingErrorOctaves": tracking_error_octaves,
                "samplePointsDb": sample_points,
            },
        }

    if hf_boost_enabled and not boost_enabled and not attenuation_enabled:
        target_frequency_hz = hf_frequency_selection_to_hz(float(params_by_name.get("pultec.hf_boost_freq_khz", 0.0)))
        peak = fr_analysis.find_peak_in_band(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            max(HF_PLOT_MIN_HZ, target_frequency_hz * 0.5),
            min(HF_PLOT_MAX_HZ, target_frequency_hz * 1.75),
        )
        width_metrics = fr_analysis.measure_peak_width(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            peak["index"],
            drop_db=HF_WIDTH_DROP_DB,
        )
        sample_points = fr_analysis.sample_points_at_frequencies(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            [HF_REFERENCE_SAMPLE_HZ, target_frequency_hz],
        )
        reference_magnitude_db = float(sample_points[fr_analysis.format_frequency_label(HF_REFERENCE_SAMPLE_HZ)])
        target_magnitude_db = float(sample_points[fr_analysis.format_frequency_label(target_frequency_hz)])
        tracking_error_octaves = abs(math.log2(peak["frequencyHz"] / target_frequency_hz))
        peak_prominence_db = float(peak["magnitudeDb"]) - reference_magnitude_db
        measurable_peak = peak_prominence_db >= HF_MIN_PEAK_GAIN_DB
        sensible_tracking = tracking_error_octaves <= HF_PEAK_TRACKING_TOLERANCE_OCTAVES
        passed = measurable_peak and sensible_tracking
        return {
            "mode": "hf_boost_only",
            "passed": passed,
            "checks": {
                "targetFrequencyHz": target_frequency_hz,
                "peakFrequencyHz": float(peak["frequencyHz"]),
                "peakMagnitudeDb": float(peak["magnitudeDb"]),
                "targetMagnitudeDb": target_magnitude_db,
                "referenceMagnitudeDb": reference_magnitude_db,
                "peakProminenceDb": peak_prominence_db,
                "minimumPeakGainDb": HF_MIN_PEAK_GAIN_DB,
                "trackingErrorOctaves": tracking_error_octaves,
                "maximumTrackingErrorOctaves": HF_PEAK_TRACKING_TOLERANCE_OCTAVES,
                "bandwidthNormalized": hf_bandwidth_normalized,
                "bandwidthLabel": hf_bandwidth_value_to_label(hf_bandwidth_normalized),
                "widthDropDb": HF_WIDTH_DROP_DB,
                "widthLowerFrequencyHz": width_metrics["lowerFrequencyHz"],
                "widthUpperFrequencyHz": width_metrics["upperFrequencyHz"],
                "widthHz": width_metrics["widthHz"],
                "widthOctaves": width_metrics["widthOctaves"],
                "samplePointsDb": sample_points,
            },
        }

    if hf_attenuation_enabled and not hf_boost_enabled and not boost_enabled and not attenuation_enabled:
        selector_frequency_hz = hf_attenuation_selection_to_hz(float(params_by_name.get("pultec.hf_atten_sel_khz", 0.0)))
        sample_points = fr_analysis.sample_points_at_frequencies(
            analysis["frequenciesHz"],
            analysis["magnitudeDb"],
            [HF_REFERENCE_SAMPLE_HZ, 5000.0, 10000.0, 20000.0],
        )
        reference_magnitude_db = float(sample_points[fr_analysis.format_frequency_label(HF_REFERENCE_SAMPLE_HZ)])
        attenuation_at_5k_db = reference_magnitude_db - float(sample_points["5000Hz"])
        attenuation_at_10k_db = reference_magnitude_db - float(sample_points["10000Hz"])
        attenuation_at_20k_db = reference_magnitude_db - float(sample_points["20000Hz"])
        selector_label = fr_analysis.format_frequency_label(selector_frequency_hz)
        selector_attenuation_db = reference_magnitude_db - float(sample_points[selector_label])
        monotonic_increase = (
            attenuation_at_5k_db <= attenuation_at_10k_db + HF_ATTENUATION_MONOTONIC_TOLERANCE_DB
            and attenuation_at_10k_db <= attenuation_at_20k_db + HF_ATTENUATION_MONOTONIC_TOLERANCE_DB
        )
        upper_region_engaged = attenuation_at_20k_db >= HF_ATTENUATION_MIN_20K_DB
        selected_region_engaged = selector_attenuation_db >= 0.5
        passed = monotonic_increase and upper_region_engaged and selected_region_engaged
        return {
            "mode": "hf_atten_only",
            "passed": passed,
            "checks": {
                "selectorFrequencyHz": selector_frequency_hz,
                "referenceMagnitudeDb": reference_magnitude_db,
                "attenuationAt5kDb": attenuation_at_5k_db,
                "attenuationAt10kDb": attenuation_at_10k_db,
                "attenuationAt20kDb": attenuation_at_20k_db,
                "selectorAttenuationDb": selector_attenuation_db,
                "minimum20kAttenuationDb": HF_ATTENUATION_MIN_20K_DB,
                "monotonicIncreaseWithinTolerance": monotonic_increase,
                "monotonicToleranceDb": HF_ATTENUATION_MONOTONIC_TOLERANCE_DB,
                "upperRegionEngaged": upper_region_engaged,
                "selectedRegionEngaged": selected_region_engaged,
                "samplePointsDb": sample_points,
            },
        }

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

    if mode == "hf_boost_only":
        return (
            "FR provisional checks failed: "
            f"target {checks.get('targetFrequencyHz', 0.0):.0f} Hz, "
            f"peak {checks.get('peakFrequencyHz', 0.0):.0f} Hz, "
            f"prominence {checks.get('peakProminenceDb', 0.0):.2f} dB, "
            f"trackingErrorOctaves={checks.get('trackingErrorOctaves', 0.0):.3f}, "
            f"widthOctaves={checks.get('widthOctaves')}"
        )

    if mode == "hf_atten_only":
        return (
            "FR provisional checks failed: "
            f"selector {checks.get('selectorFrequencyHz', 0.0):.0f} Hz, "
            f"attenuationAt5k={checks.get('attenuationAt5kDb', 0.0):.2f} dB, "
            f"attenuationAt10k={checks.get('attenuationAt10kDb', 0.0):.2f} dB, "
            f"attenuationAt20k={checks.get('attenuationAt20kDb', 0.0):.2f} dB"
        )

    if mode == "hf_boost_and_attenuation":
        return (
            "FR provisional checks failed: "
            f"target {checks.get('targetFrequencyHz', 0.0):.0f} Hz, "
            f"selector {checks.get('selectorFrequencyHz', 0.0):.0f} Hz, "
            f"peak {checks.get('peakFrequencyHz', 0.0):.0f} Hz, "
            f"peakProminence={checks.get('peakProminenceDb', 0.0):.2f} dB, "
            f"attenuationAt20k={checks.get('attenuationAt20kDb', 0.0):.2f} dB"
        )

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


def build_hf_reference_case_definition(case_definition: dict, boost_amount: float, attenuation_amount: float) -> dict:
    reference_case = copy.deepcopy(case_definition)
    params_by_name = reference_case.setdefault("paramsByName", {})
    params_by_name["pultec.hf_boost_db"] = boost_amount
    params_by_name["pultec.hf_atten_db"] = attenuation_amount
    return reference_case


def reference_cache_key(case_definition: dict) -> tuple[float, float, float]:
    params_by_name = case_definition.get("paramsByName", {})
    return (
        float(params_by_name.get("pultec.lf_freq_hz", 0.0)),
        float(params_by_name.get("pultec.lf_boost_db", 0.0)),
        float(params_by_name.get("pultec.lf_atten_db", 0.0)),
    )


def hf_reference_cache_key(case_definition: dict) -> tuple[float, float, float, float, float]:
    params_by_name = case_definition.get("paramsByName", {})
    return (
        float(params_by_name.get("pultec.hf_boost_freq_khz", 0.0)),
        float(params_by_name.get("pultec.hf_boost_db", 0.0)),
        float(params_by_name.get("pultec.hf_bandwidth", 0.5)),
        float(params_by_name.get("pultec.hf_atten_sel_khz", 0.0)),
        float(params_by_name.get("pultec.hf_atten_db", 0.0)),
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


def render_reference_hf_fr_case(
    harness_path: pathlib.Path,
    plugin_path: pathlib.Path,
    dry_impulse_path: pathlib.Path,
    output_root: pathlib.Path,
    sample_rate: int,
    block_size: int,
    case_definition: dict,
    reference_label: str,
    reference_cache: dict[tuple[float, float, float, float, float], dict],
) -> dict:
    cache_key = hf_reference_cache_key(case_definition)
    if cache_key in reference_cache:
        return reference_cache[cache_key]

    boost_freq_norm, boost_norm, bandwidth_norm, atten_sel_norm, atten_norm = cache_key
    reference_name = (
        f"hf_boost_freq_{boost_freq_norm:.7f}__boost_{boost_norm:.7f}__bw_{bandwidth_norm:.7f}__"
        f"atten_sel_{atten_sel_norm:.7f}__atten_{atten_norm:.7f}__{reference_label}"
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
        "analysis": analysis,
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


def build_hf_interaction_comparison(
    case_name: str,
    case_root: pathlib.Path,
    combined_analysis: dict,
    boost_reference: dict,
    attenuation_reference: dict,
    boost_frequency_hz: float,
    attenuation_selector_hz: float,
) -> dict:
    frequencies_hz = combined_analysis["frequenciesHz"]
    combined_magnitude_db = combined_analysis["magnitudeDb"]
    additive_magnitude_db = boost_reference["analysis"]["magnitudeDb"] + attenuation_reference["analysis"]["magnitudeDb"]
    deviation_from_additive_db = combined_magnitude_db - additive_magnitude_db

    mask = (frequencies_hz >= 2000.0) & (frequencies_hz <= 20000.0)
    if not mask.any():
        raise RuntimeError("No HF bins available for interaction comparison")

    band_indices = np.flatnonzero(mask)
    max_relative_index = int(np.argmax(np.abs(deviation_from_additive_db[mask])))
    max_index = int(band_indices[max_relative_index])
    sample_frequencies_hz = [1000.0, boost_frequency_hz, attenuation_selector_hz, 20000.0]
    combined_points = fr_analysis.sample_points_at_frequencies(frequencies_hz, combined_magnitude_db, sample_frequencies_hz)
    additive_points = fr_analysis.sample_points_at_frequencies(frequencies_hz, additive_magnitude_db, sample_frequencies_hz)
    deviation_points = {
        label: float(combined_points[label] - additive_points[label])
        for label in combined_points
    }
    boost_label = fr_analysis.format_frequency_label(boost_frequency_hz)
    max_abs_deviation_db = abs(float(deviation_from_additive_db[max_index]))
    boost_retention_delta_db = float(deviation_points[boost_label])
    not_simple_additive = max_abs_deviation_db >= HF_COMBINED_MIN_DEVIATION_FROM_ADDITIVE_DB
    note = (
        f"Combined response deviates from the additive expectation by {max_abs_deviation_db:.2f} dB at "
        f"{float(frequencies_hz[max_index]):.1f} Hz, with {boost_retention_delta_db:.2f} dB extra energy at the boost center."
        if not_simple_additive
        else (
            f"Combined response stays within {max_abs_deviation_db:.2f} dB of the additive expectation "
            f"across the HF band."
        )
    )
    comparison = {
        "case": case_name,
        "boostOnly": {
            "metricsPath": boost_reference["metricsPath"],
            "samplePointsDb": fr_analysis.sample_points_at_frequencies(
                frequencies_hz,
                boost_reference["analysis"]["magnitudeDb"],
                sample_frequencies_hz,
            ),
        },
        "attenOnly": {
            "metricsPath": attenuation_reference["metricsPath"],
            "samplePointsDb": fr_analysis.sample_points_at_frequencies(
                frequencies_hz,
                attenuation_reference["analysis"]["magnitudeDb"],
                sample_frequencies_hz,
            ),
        },
        "combined": {
            "samplePointsDb": combined_points,
        },
        "additiveExpectationDb": additive_points,
        "deviationFromAdditiveDb": deviation_points,
        "maxAbsDeviationDb": max_abs_deviation_db,
        "maxAbsDeviationFrequencyHz": float(frequencies_hz[max_index]),
        "boostCenterDeltaDb": boost_retention_delta_db,
        "notSimpleAdditive": not_simple_additive,
        "minimumDeviationDb": HF_COMBINED_MIN_DEVIATION_FROM_ADDITIVE_DB,
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


def build_hf_bandwidth_comparisons(
    output_root: pathlib.Path,
    fr_results: dict[str, dict],
    metrics_index: dict[str, dict],
) -> dict | None:
    grouped_cases: dict[int, dict[str, tuple[str, dict]]] = {}
    for case_name, result in fr_results.items():
        if "_bw_" not in case_name:
            continue

        provisional = result.get("analysis", {}).get("provisional")
        if provisional is None or provisional.get("mode") != "hf_boost_only":
            continue

        checks = provisional.get("checks", {})
        bandwidth_label = checks.get("bandwidthLabel")
        width_octaves = checks.get("widthOctaves")
        target_frequency_hz = checks.get("targetFrequencyHz")
        if bandwidth_label is None or width_octaves is None or target_frequency_hz is None:
            continue

        grouped_cases.setdefault(int(round(float(target_frequency_hz))), {})[str(bandwidth_label)] = (case_name, checks)

    if not grouped_cases:
        return None

    comparisons: dict[str, dict] = {}
    for target_frequency_hz, variants in grouped_cases.items():
        comparison = {
            "targetFrequencyHz": float(target_frequency_hz),
            "cases": {},
            "minimumWidthOrderMarginOctaves": HF_BANDWIDTH_ORDER_MARGIN_OCTAVES,
            "pass": False,
            "message": "",
        }

        missing_labels = [label for label in ("sharp", "mid", "broad") if label not in variants]
        if missing_labels:
            comparison["message"] = f"Missing bandwidth cases: {', '.join(missing_labels)}"
            comparisons[str(target_frequency_hz)] = comparison
            continue

        width_by_label = {label: float(variants[label][1]["widthOctaves"]) for label in ("sharp", "mid", "broad")}
        ordering_pass = (
            width_by_label["sharp"] + HF_BANDWIDTH_ORDER_MARGIN_OCTAVES < width_by_label["mid"]
            and width_by_label["mid"] + HF_BANDWIDTH_ORDER_MARGIN_OCTAVES < width_by_label["broad"]
        )

        for label in ("sharp", "mid", "broad"):
            case_name, checks = variants[label]
            comparison["cases"][label] = {
                "case": case_name,
                "peakFrequencyHz": float(checks["peakFrequencyHz"]),
                "peakMagnitudeDb": float(checks["peakMagnitudeDb"]),
                "widthOctaves": float(checks["widthOctaves"]),
                "widthHz": float(checks["widthHz"]),
            }

        comparison["pass"] = ordering_pass
        comparison["message"] = (
            "OK"
            if ordering_pass
            else (
                f"Width ordering failed: sharp={width_by_label['sharp']:.4f}, "
                f"mid={width_by_label['mid']:.4f}, broad={width_by_label['broad']:.4f}"
            )
        )
        comparisons[str(target_frequency_hz)] = comparison

        for label in ("sharp", "mid", "broad"):
            case_name, _ = variants[label]
            result = fr_results[case_name]
            result.setdefault("analysis", {})["bandwidthComparison"] = comparison
            metrics_index[case_name]["bandwidthComparison"] = comparison
            result["pass"] = bool(result["pass"]) and ordering_pass
            if not ordering_pass:
                result["message"] = comparison["message"]
            metrics_index[case_name]["pass"] = result["pass"]

    comparisons_path = output_root / "hf_bandwidth_comparisons.json"
    comparisons_path.write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    return {
        "path": str(comparisons_path.resolve()),
        "results": comparisons,
    }


def build_hf_attenuation_comparisons(
    output_root: pathlib.Path,
    fr_results: dict[str, dict],
    metrics_index: dict[str, dict],
) -> dict | None:
    selected_cases: dict[int, tuple[str, dict]] = {}
    for case_name, result in fr_results.items():
        if not case_name.startswith("fr_pultec_hf_atten_"):
            continue

        provisional = result.get("analysis", {}).get("provisional")
        if provisional is None or provisional.get("mode") != "hf_atten_only":
            continue

        checks = provisional.get("checks", {})
        selector_frequency_hz = checks.get("selectorFrequencyHz")
        if selector_frequency_hz is None:
            continue

        selected_cases[int(round(float(selector_frequency_hz)))] = (case_name, checks)

    if not selected_cases:
        return None

    comparison = {
        "cases": {},
        "minimumDistinctMarginDb": HF_ATTENUATION_DISTINCT_MARGIN_DB,
        "pass": False,
        "message": "",
    }

    missing_selectors = [
        selector_hz
        for selector_hz in (5000, 10000, 20000)
        if selector_hz not in selected_cases
    ]
    if missing_selectors:
        comparison["message"] = f"Missing attenuation cases: {', '.join(str(selector_hz) for selector_hz in missing_selectors)}"
    else:
        for selector_hz, (case_name, checks) in selected_cases.items():
            comparison["cases"][str(selector_hz)] = {
                "case": case_name,
                "attenuationAt5kDb": float(checks["attenuationAt5kDb"]),
                "attenuationAt10kDb": float(checks["attenuationAt10kDb"]),
                "attenuationAt20kDb": float(checks["attenuationAt20kDb"]),
            }

        attenuation_5k = comparison["cases"]["5000"]
        attenuation_10k = comparison["cases"]["10000"]
        attenuation_20k = comparison["cases"]["20000"]
        distinct_pass = (
            attenuation_5k["attenuationAt5kDb"] > attenuation_10k["attenuationAt5kDb"] + HF_ATTENUATION_DISTINCT_MARGIN_DB
            and attenuation_10k["attenuationAt5kDb"] > attenuation_20k["attenuationAt5kDb"] + HF_ATTENUATION_DISTINCT_MARGIN_DB
            and attenuation_5k["attenuationAt10kDb"] > attenuation_10k["attenuationAt10kDb"] + HF_ATTENUATION_DISTINCT_MARGIN_DB
            and attenuation_10k["attenuationAt10kDb"] > attenuation_20k["attenuationAt10kDb"] + HF_ATTENUATION_DISTINCT_MARGIN_DB
        )
        comparison["pass"] = distinct_pass
        comparison["message"] = (
            "OK"
            if distinct_pass
            else (
                f"Selector distinction failed: 5k@10k={attenuation_5k['attenuationAt10kDb']:.2f}, "
                f"10k@10k={attenuation_10k['attenuationAt10kDb']:.2f}, "
                f"20k@10k={attenuation_20k['attenuationAt10kDb']:.2f}"
            )
        )

        for _, (case_name, _) in selected_cases.items():
            result = fr_results[case_name]
            result.setdefault("analysis", {})["attenuationComparison"] = comparison
            metrics_index[case_name]["attenuationComparison"] = comparison
            result["pass"] = bool(result["pass"]) and bool(comparison["pass"])
            if not comparison["pass"]:
                result["message"] = comparison["message"]
            metrics_index[case_name]["pass"] = result["pass"]

    comparisons_path = output_root / "hf_attenuation_comparisons.json"
    comparisons_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    return {
        "path": str(comparisons_path.resolve()),
        "results": comparison,
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
    hf_reference_cache: dict[tuple[float, float, float, float, float], dict] = {}

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
            provisional = evaluate_fr_checks(result["caseDefinition"], analysis)
            write_fr_metrics_json(metrics_path, analysis, provisional)
            fr_analysis.write_curve_csv(curve_path, analysis["frequenciesHz"], analysis["magnitudeDb"])
            plot_min_hz = fr_analysis.DEFAULT_PLOT_MIN_HZ
            plot_max_hz = None
            plot_title = "Frequency Response Check"
            if provisional["mode"] in ("hf_boost_only", "hf_atten_only", "hf_boost_and_attenuation"):
                plot_min_hz = HF_PLOT_MIN_HZ
                plot_max_hz = HF_PLOT_MAX_HZ
                plot_title = (
                    "HF Boost Frequency Response Check"
                    if provisional["mode"] == "hf_boost_only"
                    else "HF Attenuation Frequency Response Check"
                    if provisional["mode"] == "hf_atten_only"
                    else "HF Combined Frequency Response Check"
                )
            fr_analysis.save_plot(
                plot_path,
                analysis["frequenciesHz"],
                analysis["magnitudeDb"],
                x_min_hz=plot_min_hz,
                x_max_hz=plot_max_hz,
                title=plot_title,
            )

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
            hf_boost_amount = float(params_by_name.get("pultec.hf_boost_db", 0.0))
            hf_attenuation_amount = float(params_by_name.get("pultec.hf_atten_db", 0.0))
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
            elif hf_boost_amount > 0.0 and hf_attenuation_amount > 0.0:
                boost_frequency_hz = hf_frequency_selection_to_hz(float(params_by_name.get("pultec.hf_boost_freq_khz", 0.0)))
                attenuation_selector_hz = hf_attenuation_selection_to_hz(float(params_by_name.get("pultec.hf_atten_sel_khz", 0.0)))
                boost_reference = render_reference_hf_fr_case(
                    harness_path=harness_path,
                    plugin_path=plugin_path,
                    dry_impulse_path=dry_impulse_path,
                    output_root=output_root,
                    sample_rate=sample_rate,
                    block_size=block_size,
                    case_definition=build_hf_reference_case_definition(result["caseDefinition"], hf_boost_amount, 0.0),
                    reference_label="boost_only",
                    reference_cache=hf_reference_cache,
                )
                attenuation_reference = render_reference_hf_fr_case(
                    harness_path=harness_path,
                    plugin_path=plugin_path,
                    dry_impulse_path=dry_impulse_path,
                    output_root=output_root,
                    sample_rate=sample_rate,
                    block_size=block_size,
                    case_definition=build_hf_reference_case_definition(result["caseDefinition"], 0.0, hf_attenuation_amount),
                    reference_label="atten_only",
                    reference_cache=hf_reference_cache,
                )
                interaction_comparison = build_hf_interaction_comparison(
                    case_name=case_name,
                    case_root=case_root,
                    combined_analysis=analysis,
                    boost_reference=boost_reference,
                    attenuation_reference=attenuation_reference,
                    boost_frequency_hz=boost_frequency_hz,
                    attenuation_selector_hz=attenuation_selector_hz,
                )
                result["analysis"]["interactionComparison"] = interaction_comparison

            result["pass"] = bool(provisional["passed"])
            if "interactionComparison" in result["analysis"]:
                interaction_pass = (
                    bool(result["analysis"]["interactionComparison"].get("notSimpleCancellation"))
                    if provisional["mode"] == "boost_and_attenuation"
                    else bool(result["analysis"]["interactionComparison"].get("notSimpleAdditive"))
                )
                result["pass"] = result["pass"] and interaction_pass
            result["message"] = (
                "OK"
                if result["pass"]
                else result["analysis"]["interactionComparison"]["note"]
                if (
                    "interactionComparison" in result["analysis"]
                    and provisional["passed"]
                    and (
                        (
                            provisional["mode"] == "boost_and_attenuation"
                            and not result["analysis"]["interactionComparison"].get("notSimpleCancellation", False)
                        )
                        or (
                            provisional["mode"] == "hf_boost_and_attenuation"
                            and not result["analysis"]["interactionComparison"].get("notSimpleAdditive", False)
                        )
                    )
                )
                else format_fr_failure(provisional)
            )
            metrics_index[case_name] = {
                "case": case_name,
                "metricsPath": str(metrics_path.resolve()),
                "curveCsvPath": str(curve_path.resolve()),
                "plotPath": str(plot_path.resolve()),
                "pointsDb": result["analysis"]["pointsDb"],
                "shiftSamples": result["analysis"]["shiftSamples"],
                "provisional": provisional,
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

    bandwidth_comparisons = build_hf_bandwidth_comparisons(output_root, fr_results, metrics_index)
    if bandwidth_comparisons is not None:
        failed_case_set = set(failed_cases)
        for case_name, result in fr_results.items():
            if not result["pass"]:
                failed_case_set.add(case_name)
        failed_cases = sorted(failed_case_set)

    attenuation_comparisons = build_hf_attenuation_comparisons(output_root, fr_results, metrics_index)
    if attenuation_comparisons is not None:
        failed_case_set = set(failed_cases)
        for case_name, result in fr_results.items():
            if not result["pass"]:
                failed_case_set.add(case_name)
        failed_cases = sorted(failed_case_set)

    return {
        "results": metrics_index,
        "failedCases": failed_cases,
        "hfBandwidthComparisons": bandwidth_comparisons,
        "hfAttenuationComparisons": attenuation_comparisons,
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
