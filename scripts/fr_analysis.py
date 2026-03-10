from __future__ import annotations

import binascii
import csv
import json
import math
import pathlib
import struct
import wave
import zlib

import numpy as np

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    plt = None


CHECK_FREQUENCIES_HZ = [20.0, 30.0, 60.0, 100.0, 200.0]
FFT_EPSILON = 1.0e-12
DEFAULT_PLOT_MIN_HZ = 10.0
DEFAULT_PLOT_MAX_HZ = 20000.0
PLOT_PADDING_DB = 3.0


def read_wav_mono(path: pathlib.Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav_file:
        num_channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        num_frames = wav_file.getnframes()
        raw = wav_file.readframes(num_frames)

    if sample_width == 3:
        data = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        signed = (
            data[:, 0].astype(np.int32)
            | (data[:, 1].astype(np.int32) << 8)
            | (data[:, 2].astype(np.int32) << 16)
        )
        signed = np.where(signed & 0x800000, signed - 0x1000000, signed)
        audio = signed.astype(np.float32) / 8388608.0
    elif sample_width == 2:
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width * 8} bits")

    audio = audio.reshape(-1, num_channels)
    return np.mean(audio, axis=1), sample_rate


def align_impulse(dry: np.ndarray, wet: np.ndarray) -> np.ndarray:
    aligned_wet, _ = align_impulse_with_shift(dry, wet)
    return aligned_wet


def align_impulse_with_shift(dry: np.ndarray, wet: np.ndarray) -> tuple[np.ndarray, int]:
    dry_peak = int(np.argmax(np.abs(dry)))
    wet_peak = int(np.argmax(np.abs(wet)))
    shift = wet_peak - dry_peak

    if shift > 0:
        wet = wet[shift:]
    elif shift < 0:
        wet = np.pad(wet, (abs(shift), 0))

    if wet.shape[0] < dry.shape[0]:
        wet = np.pad(wet, (0, dry.shape[0] - wet.shape[0]))

    return wet[: dry.shape[0]], shift


def compute_spectrum(signal: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    fft_size = 1 << math.ceil(math.log2(max(len(signal), 1)))
    spectrum = np.fft.rfft(signal, n=fft_size)
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    return frequencies, spectrum


def compute_frequency_response(signal: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frequencies, spectrum = compute_spectrum(signal, sample_rate)
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), FFT_EPSILON))
    return frequencies, magnitude_db


def format_frequency_label(frequency_hz: float) -> str:
    rounded = round(float(frequency_hz))
    if abs(float(frequency_hz) - rounded) < 1.0e-6:
        return f"{int(rounded)}Hz"
    return f"{float(frequency_hz):.1f}Hz"


def sample_points_at_frequencies(
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    frequencies_hz: list[float],
) -> dict[str, float]:
    points: dict[str, float] = {}
    for frequency_hz in frequencies_hz:
        index = int(np.argmin(np.abs(frequencies - frequency_hz)))
        points[format_frequency_label(frequency_hz)] = float(magnitude_db[index])
    return points


def sample_points(frequencies: np.ndarray, magnitude_db: np.ndarray) -> dict[str, float]:
    return sample_points_at_frequencies(frequencies, magnitude_db, CHECK_FREQUENCIES_HZ)


def find_peak_in_band(
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    min_frequency_hz: float,
    max_frequency_hz: float,
) -> dict[str, float]:
    mask = (frequencies >= min_frequency_hz) & (frequencies <= max_frequency_hz)
    if not np.any(mask):
        raise ValueError(f"No FFT bins available in band {min_frequency_hz} Hz .. {max_frequency_hz} Hz")

    band_indices = np.flatnonzero(mask)
    peak_relative_index = int(np.argmax(magnitude_db[mask]))
    peak_index = int(band_indices[peak_relative_index])
    return {
        "frequencyHz": float(frequencies[peak_index]),
        "magnitudeDb": float(magnitude_db[peak_index]),
        "index": peak_index,
    }


def interpolate_crossing_frequency(
    frequency_a_hz: float,
    magnitude_a_db: float,
    frequency_b_hz: float,
    magnitude_b_db: float,
    target_magnitude_db: float,
) -> float:
    if abs(magnitude_b_db - magnitude_a_db) < 1.0e-9:
        return float(frequency_b_hz)

    ratio = (target_magnitude_db - magnitude_a_db) / (magnitude_b_db - magnitude_a_db)
    clamped_ratio = min(1.0, max(0.0, float(ratio)))
    log_frequency_a = math.log(float(frequency_a_hz))
    log_frequency_b = math.log(float(frequency_b_hz))
    return float(math.exp(log_frequency_a + (log_frequency_b - log_frequency_a) * clamped_ratio))


def measure_peak_width(
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    peak_index: int,
    drop_db: float = 3.0,
) -> dict[str, float | None]:
    peak_index = int(peak_index)
    peak_frequency_hz = float(frequencies[peak_index])
    peak_magnitude_db = float(magnitude_db[peak_index])
    target_magnitude_db = peak_magnitude_db - float(drop_db)

    lower_frequency_hz: float | None = None
    for index in range(peak_index, 0, -1):
        previous_index = index - 1
        if float(magnitude_db[previous_index]) <= target_magnitude_db <= float(magnitude_db[index]):
            lower_frequency_hz = interpolate_crossing_frequency(
                float(frequencies[index]),
                float(magnitude_db[index]),
                float(frequencies[previous_index]),
                float(magnitude_db[previous_index]),
                target_magnitude_db,
            )
            break

    upper_frequency_hz: float | None = None
    for index in range(peak_index, len(frequencies) - 1):
        next_index = index + 1
        if float(magnitude_db[next_index]) <= target_magnitude_db <= float(magnitude_db[index]):
            upper_frequency_hz = interpolate_crossing_frequency(
                float(frequencies[index]),
                float(magnitude_db[index]),
                float(frequencies[next_index]),
                float(magnitude_db[next_index]),
                target_magnitude_db,
            )
            break

    width_hz = None
    width_octaves = None
    if lower_frequency_hz is not None and upper_frequency_hz is not None and lower_frequency_hz > 0.0:
        width_hz = float(upper_frequency_hz - lower_frequency_hz)
        width_octaves = float(math.log2(upper_frequency_hz / lower_frequency_hz))

    return {
        "peakFrequencyHz": peak_frequency_hz,
        "peakMagnitudeDb": peak_magnitude_db,
        "targetMagnitudeDb": target_magnitude_db,
        "lowerFrequencyHz": lower_frequency_hz,
        "upperFrequencyHz": upper_frequency_hz,
        "widthHz": width_hz,
        "widthOctaves": width_octaves,
        "dropDb": float(drop_db),
    }


def analyze_frequency_response_arrays(dry: np.ndarray, wet: np.ndarray, sample_rate: int) -> dict:
    aligned_wet, shift_samples = align_impulse_with_shift(dry, wet)
    aligned_dry = dry[: aligned_wet.shape[0]]
    frequencies, wet_spectrum = compute_spectrum(aligned_wet, sample_rate)
    _, dry_spectrum = compute_spectrum(aligned_dry, sample_rate)
    transfer_function = wet_spectrum / np.maximum(np.abs(dry_spectrum), FFT_EPSILON)
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(transfer_function), FFT_EPSILON))
    points = sample_points(frequencies, magnitude_db)
    return {
        "sampleRate": sample_rate,
        "shiftSamples": int(shift_samples),
        "frequenciesHz": frequencies,
        "magnitudeDb": magnitude_db,
        "pointsDb": points,
    }


def analyze_frequency_response_files(dry_path: pathlib.Path, wet_path: pathlib.Path) -> dict:
    dry, dry_sample_rate = read_wav_mono(dry_path)
    wet, wet_sample_rate = read_wav_mono(wet_path)
    if dry_sample_rate != wet_sample_rate:
        raise ValueError(f"Sample rate mismatch: dry={dry_sample_rate}, wet={wet_sample_rate}")
    return analyze_frequency_response_arrays(dry, wet, wet_sample_rate)


def resolve_plot_range(frequencies: np.ndarray, x_min_hz: float, x_max_hz: float | None) -> tuple[float, float]:
    effective_max_hz = float(frequencies[-1]) if frequencies.size > 0 else DEFAULT_PLOT_MAX_HZ
    max_hz = min(DEFAULT_PLOT_MAX_HZ, effective_max_hz) if x_max_hz is None else min(float(x_max_hz), effective_max_hz)
    min_hz = max(DEFAULT_PLOT_MIN_HZ, float(x_min_hz))
    if max_hz <= min_hz:
        max_hz = max(min_hz * 2.0, min(DEFAULT_PLOT_MAX_HZ, effective_max_hz))
    return min_hz, max_hz


def save_plot(
    out_path: pathlib.Path,
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    x_min_hz: float = DEFAULT_PLOT_MIN_HZ,
    x_max_hz: float | None = None,
    title: str = "Frequency Response Check",
) -> None:
    plot_min_hz, plot_max_hz = resolve_plot_range(frequencies, x_min_hz, x_max_hz)

    if plt is None:
        save_simple_png(out_path, frequencies, magnitude_db, plot_min_hz, plot_max_hz, title)
        return

    mask = (frequencies >= plot_min_hz) & (frequencies <= plot_max_hz)
    if not np.any(mask):
        raise ValueError(f"No FFT bins available in plot range {plot_min_hz} Hz .. {plot_max_hz} Hz")

    plot_magnitude = magnitude_db[mask]
    plt.figure(figsize=(8, 4.5))
    plt.semilogx(frequencies[1:], magnitude_db[1:], linewidth=1.5)
    plt.xlim(plot_min_hz, plot_max_hz)
    plt.ylim(
        np.min(plot_magnitude) - PLOT_PADDING_DB,
        np.max(plot_magnitude) + PLOT_PADDING_DB,
    )
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Magnitude (dB)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def write_png(path: pathlib.Path, image: np.ndarray) -> None:
    height, width, _ = image.shape

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    raw_rows = b"".join(b"\x00" + image[row].tobytes() for row in range(height))
    png_bytes = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw_rows, level=9)),
            chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(png_bytes)


def draw_line(image: np.ndarray, x0: int, y0: int, x1: int, y1: int, colour: tuple[int, int, int]) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        if 0 <= x0 < image.shape[1] and 0 <= y0 < image.shape[0]:
            image[y0, x0] = colour
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def save_simple_png(
    out_path: pathlib.Path,
    frequencies: np.ndarray,
    magnitude_db: np.ndarray,
    x_min_hz: float,
    x_max_hz: float,
    title: str,
) -> None:
    width = 1000
    height = 600
    margin_left = 70
    margin_right = 20
    margin_top = 20
    margin_bottom = 50
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    mask = (frequencies >= x_min_hz) & (frequencies <= x_max_hz)
    plot_freqs = frequencies[mask]
    plot_mag = magnitude_db[mask]

    if plot_freqs.size == 0:
        raise ValueError(f"No FFT bins available in plot range {x_min_hz} Hz .. {x_max_hz} Hz")

    y_min = float(np.min(plot_mag) - PLOT_PADDING_DB)
    y_max = float(np.max(plot_mag) + PLOT_PADDING_DB)
    x_min = math.log10(x_min_hz)
    x_max = math.log10(x_max_hz)

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    axis_colour = (180, 180, 180)
    line_colour = (30, 90, 200)

    x_axis_y = height - margin_bottom
    y_axis_x = margin_left
    image[margin_top:x_axis_y + 1, y_axis_x] = axis_colour
    image[x_axis_y, y_axis_x:width - margin_right] = axis_colour

    previous_x = None
    previous_y = None
    for freq, mag in zip(plot_freqs, plot_mag):
        x = int(round(((math.log10(float(freq)) - x_min) / (x_max - x_min)) * (plot_width - 1))) + margin_left
        y = int(round(((y_max - float(mag)) / (y_max - y_min)) * (plot_height - 1))) + margin_top
        if previous_x is not None:
            draw_line(image, previous_x, previous_y, x, y, line_colour)
        previous_x = x
        previous_y = y

    write_png(out_path, image)


def write_curve_csv(out_path: pathlib.Path, frequencies: np.ndarray, magnitude_db: np.ndarray) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["frequency_hz", "magnitude_db"])
        for frequency_hz, magnitude in zip(frequencies, magnitude_db):
            writer.writerow([f"{float(frequency_hz):.9f}", f"{float(magnitude):.9f}"])


def serialise_metrics(analysis: dict) -> dict:
    return {
        "sampleRate": int(analysis["sampleRate"]),
        "shiftSamples": int(analysis["shiftSamples"]),
        "pointsDb": {label: float(value) for label, value in analysis["pointsDb"].items()},
        "checkFrequenciesHz": [float(frequency_hz) for frequency_hz in CHECK_FREQUENCIES_HZ],
    }


def write_metrics_json(out_path: pathlib.Path, analysis: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(serialise_metrics(analysis), indent=2), encoding="utf-8")
