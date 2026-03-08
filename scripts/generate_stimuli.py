#!/usr/bin/env python3
import argparse
import math
import pathlib
import wave

import numpy as np


DEFAULT_SAMPLE_RATE = 48000
DEFAULT_OUTDIR = pathlib.Path("tests/_generated")
DEFAULT_CHANNELS = 2
PCM24_MAX = (1 << 23) - 1
PCM24_MIN = -(1 << 23)
PEAK_M18_DBFS = 10.0 ** (-18.0 / 20.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic measurement stimuli WAVs.")
    parser.add_argument("--sr", type=int, default=DEFAULT_SAMPLE_RATE, help="Sample rate in Hz")
    parser.add_argument("--outdir", type=pathlib.Path, default=DEFAULT_OUTDIR, help="Output directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    return parser.parse_args()


def to_stereo(signal: np.ndarray) -> np.ndarray:
    return np.repeat(signal[:, np.newaxis], DEFAULT_CHANNELS, axis=1)


def quantize_pcm24(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    scaled = np.rint(clipped * PCM24_MAX).astype(np.int32)
    scaled = np.clip(scaled, PCM24_MIN, PCM24_MAX)

    packed = np.empty((scaled.size, 3), dtype=np.uint8)
    flat = scaled.reshape(-1)
    packed[:, 0] = flat & 0xFF
    packed[:, 1] = (flat >> 8) & 0xFF
    packed[:, 2] = (flat >> 16) & 0xFF
    return packed.tobytes()


def write_wav24(path: pathlib.Path, audio: np.ndarray, sample_rate: int, overwrite: bool) -> str:
    if path.exists() and not overwrite:
        return f"Skipped: {path}"

    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(audio.shape[1])
        wav_file.setsampwidth(3)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(quantize_pcm24(audio))

    return f"Wrote: {path}"


def generate_impulse(sample_rate: int, seconds: float = 2.0) -> np.ndarray:
    num_samples = int(round(sample_rate * seconds))
    signal = np.zeros(num_samples, dtype=np.float64)
    signal[0] = 1.0
    return to_stereo(signal)


def generate_silence(sample_rate: int, seconds: float = 8.0) -> np.ndarray:
    num_samples = int(round(sample_rate * seconds))
    return np.zeros((num_samples, DEFAULT_CHANNELS), dtype=np.float64)


def generate_sine(sample_rate: int, frequency_hz: float, seconds: float = 8.0) -> np.ndarray:
    num_samples = int(round(sample_rate * seconds))
    t = np.arange(num_samples, dtype=np.float64) / float(sample_rate)
    signal = PEAK_M18_DBFS * np.sin(2.0 * math.pi * frequency_hz * t)
    return to_stereo(signal)


def generate_logsweep(
    sample_rate: int,
    start_hz: float = 10.0,
    end_hz: float = 22000.0,
    seconds: float = 10.0,
) -> np.ndarray:
    num_samples = int(round(sample_rate * seconds))
    t = np.arange(num_samples, dtype=np.float64) / float(sample_rate)
    ratio = end_hz / start_hz
    log_ratio = math.log(ratio)
    phase = 2.0 * math.pi * start_hz * seconds * (np.exp((t / seconds) * log_ratio) - 1.0) / log_ratio
    signal = PEAK_M18_DBFS * np.sin(phase)
    return to_stereo(signal)


def main() -> int:
    args = parse_args()

    if args.sr <= 0:
        raise ValueError("Sample rate must be positive")

    outputs = {
        "impulse.wav": generate_impulse(args.sr, seconds=2.0),
        "silence_8s.wav": generate_silence(args.sr, seconds=8.0),
        "sine_100hz_m18dbfs.wav": generate_sine(args.sr, 100.0, seconds=8.0),
        "sine_1khz_m18dbfs.wav": generate_sine(args.sr, 1000.0, seconds=8.0),
        "sine_10khz_m18dbfs.wav": generate_sine(args.sr, 10000.0, seconds=8.0),
        "logsweep_10hz_22khz_10s_m18dbfs.wav": generate_logsweep(args.sr, 10.0, 22000.0, seconds=10.0),
    }

    for filename, audio in outputs.items():
        print(write_wav24(args.outdir / filename, audio, args.sr, args.overwrite))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
