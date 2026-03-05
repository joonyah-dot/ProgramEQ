#!/usr/bin/env python3
import argparse
import json
import math
import pathlib
import wave

import numpy as np


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


def rms_dbfs(signal: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(signal), dtype=np.float64) + 1.0e-20))
    return 20.0 * math.log10(rms)


def make_window(buffer: np.ndarray, center: int, size: int) -> np.ndarray:
    start = max(0, center - (size // 2))
    end = min(buffer.shape[0], start + size)
    if end - start < size:
        start = max(0, end - size)
    return buffer[start:end]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--low", required=True, help="Wet render with LF boost at 0 percent")
    parser.add_argument("--high", required=True, help="Wet render with LF boost at 100 percent")
    parser.add_argument("--window-ms", type=float, default=1.0, help="RMS window size in milliseconds")
    parser.add_argument("--max-boundary-excess-db", type=float, default=1.0)
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    low, sample_rate_low = read_wav_mono(pathlib.Path(args.low))
    high, sample_rate_high = read_wav_mono(pathlib.Path(args.high))

    if sample_rate_low != sample_rate_high:
        raise ValueError(f"Sample rate mismatch: low={sample_rate_low}, high={sample_rate_high}")

    sample_rate = sample_rate_low
    num_samples = min(low.shape[0], high.shape[0])
    if num_samples <= 0:
        raise ValueError("Input renders must contain at least one sample")

    low = low[:num_samples]
    high = high[:num_samples]

    boundary = num_samples // 2
    stepped = np.concatenate([low[:boundary], high[boundary:]])

    # Difference filter emphasizes transient energy at the boundary.
    transient = np.empty_like(stepped)
    transient[0] = stepped[0]
    transient[1:] = stepped[1:] - stepped[:-1]

    window_samples = max(16, int(round(sample_rate * (args.window_ms / 1000.0))))
    pre_window = make_window(transient, boundary - window_samples, window_samples)
    boundary_window = make_window(transient, boundary, window_samples)
    post_window = make_window(transient, boundary + window_samples, window_samples)

    pre_rms_dbfs = rms_dbfs(pre_window)
    boundary_rms_dbfs = rms_dbfs(boundary_window)
    post_rms_dbfs = rms_dbfs(post_window)
    boundary_excess_db = boundary_rms_dbfs - max(pre_rms_dbfs, post_rms_dbfs)

    result = {
        "sampleRate": sample_rate,
        "numSamples": num_samples,
        "boundarySample": boundary,
        "windowMs": args.window_ms,
        "preRmsDbfs": pre_rms_dbfs,
        "boundaryRmsDbfs": boundary_rms_dbfs,
        "postRmsDbfs": post_rms_dbfs,
        "boundaryExcessDb": boundary_excess_db,
        "maxBoundaryExcessDb": args.max_boundary_excess_db,
        "pass": boundary_excess_db <= args.max_boundary_excess_db,
    }

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"preRmsDbfs: {pre_rms_dbfs:.2f}")
    print(f"boundaryRmsDbfs: {boundary_rms_dbfs:.2f}")
    print(f"postRmsDbfs: {post_rms_dbfs:.2f}")
    print(f"boundaryExcessDb: {boundary_excess_db:.2f}")
    print(f"maxBoundaryExcessDb: {args.max_boundary_excess_db:.2f}")

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
