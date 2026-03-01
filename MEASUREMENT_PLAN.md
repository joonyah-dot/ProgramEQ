# ProgramEQ — MEASUREMENT PLAN (Fully Automated “Sound Criteria”)

This document defines **exact stimuli**, render settings, metrics, tolerances, and file formats so that
ProgramEQ’s “sound criteria” becomes fully automated and regression-testable.

The goal is not “one perfect number,” but a stable gate that:
- detects unintended DSP drift,
- enforces EQP‑1A control-point correctness,
- validates bypass semantics,
- quantifies distortion/noise/aliasing behavior.

---

## 1) Tooling & repository integration

### 1.1 Existing infrastructure in this repo
- `tools/vst3_harness` supports:
  - `dump-params`
  - `render --case <json>`
  - `analyze --auto-align --null`
- `scripts/run_harness.ps1` already builds Release, generates test WAVs, renders an impulse, and runs analyze.

### 1.2 Proposed measurement runner (to be implemented)
Add a Python entry point:

`python scripts/run_measurements.py --plugin <path/to/ProgramEQ.vst3> [--sr 48000] [--update-goldens]`

Outputs:
- `artifacts/<timestamp>/summary.json`
- `artifacts/<timestamp>/plots/*.png`
- `artifacts/<timestamp>/tables/*.csv`
- `artifacts/<timestamp>/renders/*.wav`

Goldens (committed):
- `tests/golden/metrics_<sr>_<os>.json`

---

## 2) Common render configuration (defaults)

Unless a test specifies otherwise:

- **Sample rates:** 48 kHz (required), plus 96 kHz (recommended gate on CI if feasible)
- **Block sizes:** 64 and 256 (both required)
- **Channels:** stereo (2)
- **Warmup:** 200 ms
- **Render length:** 4.0 s (stimulus-dependent)
- **Output file format:** 24-bit PCM WAV (same as harness output)

### 2.1 Parameter conventions
All test cases set parameters using `paramsByName` normalized values in JSON case files.
Each case file is stored at `tests/cases/<name>.json`.

The harness case schema supports:
- `warmupMs` (int)
- `renderSeconds` (float)
- `paramsByName` (object: name -> normalized float 0..1)
- `paramsByIndex` (object: index -> normalized float 0..1)

---

## 3) Stimuli generation (exact definitions)

All stimuli must be deterministic given the same CLI args.

### 3.1 Impulse (linear response)
- Length: 2.0 s
- First sample = 1.0, all others = 0.0
- Used for frequency-response measurement via FFT of the aligned output

### 3.2 Log sweep (optional alternative FR method)
- Duration: 10.0 s
- Sweep: 10 Hz → 22 kHz (log)
- Level: −18 dBFS peak
- Followed by 2.0 s silence tail

### 3.3 Sine tones (distortion)
Each tone render:
- Duration: 8.0 s (use last 6.0 s for analysis after warmup)
- Frequencies: 100 Hz, 1 kHz, 10 kHz
- Levels (peak): −36, −24, −18, −12, −6 dBFS

### 3.4 Silence (noise floor)
- Duration: 8.0 s of zeros
- Used for noise metrics with analog noise on/off

### 3.5 Multi-tone (alias/stress)
- 10 sine partials, log-spaced 200 Hz–18 kHz
- Each partial at −30 dBFS peak
- Sum normalized to −18 dBFS peak

---

## 4) Analysis methods (exact)

All analysis is done offline in Python from WAV outputs.

### 4.1 Alignment
Use `vst3_harness analyze --auto-align` for a coarse alignment check, but
measurement scripts should also compute the peak of cross-correlation between dry and wet impulse
and align precisely in samples.

### 4.2 Frequency response (FR)
For linear tests (analog disabled):
1) Render impulse (dry) through plugin (wet)
2) Align wet to dry
3) Compute FFT of wet impulse response:
   - Window: Hann
   - FFT size: next pow2 >= len(impulse) (e.g., 131072 at 48k for 2s)
4) Magnitude in dB: `20*log10(|H(f)| + eps)`
5) Report metrics:
   - `mag_db_at_points`: (20, 30, 60, 100, 1k, 10k, 20k)
   - `peak_freq_hz`, `peak_gain_db` for HF boosts
   - `shelf_3db_freq_hz` for HPF
   - `max_abs_error_db` vs golden curve (sampled on log grid)

### 4.3 Distortion (THD+N)
For each sine render:
1) Take analysis window of last 6.0 s
2) Apply Hann window
3) FFT with sufficient resolution (>= 2^18 recommended at 48k)
4) Identify fundamental bin (quadratic interpolation)
5) Compute harmonics 2–10 within ±1 bin each
6) THD = sqrt(sum(harmonics^2)) / fundamental
7) THD+N = sqrt(sum(all bins except fundamental ±1 bin)^2) / fundamental
8) Report:
   - `thd_percent`, `thdn_percent`
   - harmonic levels in dBc
   - alias energy metric (see 4.4)

### 4.4 Aliasing metric
For high-frequency tone tests (10 kHz) at higher drive:
- Define “non-harmonic energy” as all bins excluding:
  - fundamental ±1 bin
  - integer harmonics up to Nyquist ±1 bin each
- Alias metric = energy(non-harmonic) / energy(fundamental)
Pass condition: oversampling 4x must reduce alias metric by at least **6 dB** vs oversampling Off.

### 4.5 Noise floor
For silence renders:
- RMS dBFS over last 6.0 s
- Peak dBFS
Targets:
- With analog noise disabled: RMS <= −140 dBFS (practically at float noise floor)
- With analog noise enabled: RMS target derived from EQP‑1A noise spec (see Section 6.3).

---

## 5) Test matrix (what we measure)

### 5.1 Smoke + null (always run)
Cases:
- `true_bypass_on`
- `pultec_flat_analog_off`
- `pultec_flat_analog_on`
- `addons_off_null`

### 5.2 EQP‑1A frequency response grid (analog off)
Run these sets at 48 kHz, blocksize 256, oversampling Off:

LF shelf boost only:
- LF FREQ = 20/30/60/100
- BOOST = {0, 25%, 50%, 75%, 100%}
- ATTEN = 0

LF shelf atten only:
- same, with ATTEN sweep

LF boost+atten interaction (“Pultec trick”):
- LF FREQ = 60 and 100
- BOOST = 75%
- ATTEN = {25%, 50%, 75%}

HF boost:
- HF FREQ = 3/4/5/8/10/12/16
- BOOST = 75%
- BANDWIDTH = {sharp, mid, broad}

HF attenuation:
- ATTEN SEL = 5/10/20
- ATTEN = {25%, 50%, 75%}
- HF BOOST = 0

### 5.3 Modern add-ons FR tests (analog off)
HPF 100:
- enabled/disabled; verify cutoff & slope

Param band 1 and 2:
- freq = 100 Hz, 1 kHz, 10 kHz
- gain = ±6, ±12 dB
- Q = 0.7, 2.0, 6.0

### 5.4 Distortion & aliasing (analog on)
At 48 kHz:
- oversampling modes: Off, 2x, 4x
- drive = {low, mid, high} (define exact values in params)
- sine tones at 100 Hz / 1 kHz / 10 kHz with level sweep

---

## 6) Pass/fail tolerances (enforced)

### 6.1 Curve correctness (hard gates)
- Enum switch frequencies must match EXACTLY (no drift).
- Max boost/cut ranges must match spec (no drift).

### 6.2 FR regression tolerance (soft numeric gates)
Compare measured FR curve against golden on a log-spaced grid (e.g., 256 points from 20 Hz–20 kHz):

- `max_abs_error_db` <= 0.5 dB (analog off)
- `avg_abs_error_db` <= 0.15 dB

### 6.3 Distortion targets (calibrated)
We calibrate: **−18 dBFS ≙ +4 dBu** (common studio reference).  
Then **+10 dBm (≈ +10 dBu at 600 Ω)** corresponds to **−12 dBFS**.

Targets (analog “low drive” mode):
- THD at 1 kHz, −12 dBFS: **0.15% ± 0.15%** (broad tolerance; tighten as model matures)
- Noise (analog noise enabled), silence: RMS around **−104 dBFS** (92 dB below +10 dBm spec)

### 6.4 Bypass semantics (gates)
- True bypass null RMS <= −120 dBFS.
- Pultec EQ OUT with analog enabled must **not** fully null (must differ by at least −90 dBFS RMS),
  confirming coloration path remains.

### 6.5 Oversampling improvement (gate)
- Aliasing metric at 10 kHz, higher drive: 4x OS must be >= 6 dB better than OS Off.

---

## 7) File formats

### 7.1 Render outputs
- WAV, 24-bit PCM
- Naming: `renders/<case>__sr48000__bs256__osOff__wet.wav`

### 7.2 Metrics outputs
- `summary.json`: top-level pass/fail + pointers to detailed files
- `tables/*.csv`: per-test metrics in tabular form
- `plots/*.png`: FR plots, harmonic spectra plots

JSON schema recommendation:
```json
{
  "version": "1",
  "plugin": { "path": "...", "build": "Release", "git_sha": "..." },
  "run": { "timestamp": "YYYYMMDD_HHMMSS", "sr": 48000, "blocksize": 256 },
  "results": [
    { "name": "fr_pultec_lf_boost_60hz_75pct", "pass": true, "metrics": { "max_abs_error_db": 0.23 } }
  ]
}
```

---

## 8) Golden update workflow

- Default behavior: compare against committed goldens and fail on regression.
- `--update-goldens`: overwrite goldens with the new metrics/curves (requires human review).

---

## 9) Notes on reference targets

Hardware control ranges, switch points, distortion and noise reference points are derived from the EQP‑1A
published specifications and documentation. The automated suite enforces switch points strictly and uses
golden curves/metrics plus tolerances for the remainder.

