# ProgramEQ — TASK BREAKDOWN (Codex-sized tickets)

This file is a backlog of small, self-contained tickets suitable for AI coding agents.

Conventions:
- Keep tickets small (0.5–2 hours of work).
- Each ticket includes a **Done When** checklist that must be satisfied.
- Prefer adding/using `tools/vst3_harness` test cases + Python analysis rather than manual listening.

---

## EPIC A — Repo hygiene + developer ergonomics (Tickets 1–8)

### 1) Reformat/minify cleanup of Source files
**Goal:** Make the JUCE plugin sources readable and diff-friendly (current files are single-line).  
**Files:** `Source/*.cpp`, `Source/*.h`  
**Done When:**
- Code is formatted (clang-format or consistent manual style).
- No behavior change (plugin still loads and passes passthrough harness run).

### 2) Add `docs/` folder and commit architecture docs
**Goal:** Create `docs/` and add links to SPEC + measurement plan.  
**Done When:** `docs/README.md` exists and points to the three key docs.

### 3) Add a standard parameter ID registry header
**Goal:** Centralize parameter IDs / metadata.  
**Files:** `Source/Parameters.h/.cpp` (new)  
**Done When:** Plugin builds and exposes at least 3 dummy parameters via `dump-params`.

### 4) Add AudioProcessorValueTreeState scaffolding
**Goal:** Use APVTS for parameters, state save/restore.  
**Done When:**
- `getStateInformation` / `setStateInformation` implemented
- Presets/automation stable across reload.

### 5) Add consistent logging/diagnostics macros (debug-only)
**Goal:** Lightweight debug logging that compiles out in Release.  
**Done When:** No allocations in audio thread; logs used in prepare/process without I/O in Release.

### 6) Add a `scripts/run_smoke.ps1`
**Goal:** Single command: build + render + null.  
**Done When:** Script runs successfully end-to-end on a clean clone.

### 7) Add a “no allocations in audio thread” guard (debug)
**Goal:** Detect accidental heap use in processBlock.  
**Done When:** Guard is active in Debug builds and documented; does not break builds.

### 8) Add `scripts/requirements.txt` for measurement tools
**Goal:** Pin Python deps used by measurement scripts (numpy/scipy/matplotlib).  
**Done When:** `pip install -r scripts/requirements.txt` works.

---

## EPIC B — EQP‑1A section (passive network) (Tickets 9–26)

### 9) Implement initial parameter set for EQP‑1A section
**Goal:** Add all `pultec.*` parameters from SPEC (enums + floats).  
**Done When:** `vst3_harness dump-params` lists them by name.

### 10) Implement parameter smoothing utility
**Goal:** One reusable smoothing class for float params.  
**Done When:** No zipper noise in automated step tests (see Ticket 46).

### 11) Add oversampling framework (Off / 2x / 4x)
**Goal:** Oversample the “analog/color + any nonlinear” block, with clean latency reporting.  
**Done When:** Switching modes works during playback without crash; plugin reports latency if needed.

### 12) Add “Pultec EQ IN/OUT” vs “True Bypass” semantics
**Goal:** Two bypass paths as defined in SPEC.  
**Done When:** Null tests behave as expected (Ticket 44, 45).

### 13) Choose and integrate passive-network modeling approach
**Goal:** Decide WDF (preferred) or equivalent topology and add it as a module.  
**Done When:** A “flat” response mode exists and is stable.

### 14) Implement LF shelf boost network (20/30/60/100)
**Done When:** Measured low shelf boost curves exist and are monotonic with gain.

### 15) Implement LF shelf attenuation network
**Done When:** Attenuation curves match expected behavior and range.

### 16) Implement LF Boost+Atten interactive behavior (“Pultec trick”)
**Done When:** The curve family shows boost+dip interaction (Measurement suite test).

### 17) Implement HF peak boost center frequency selector
**Done When:** Peaks occur near selected frequencies at nominal bandwidth.

### 18) Implement HF bandwidth control (sharp↔broad)
**Done When:** Peak width changes continuously and smoothly across knob range.

### 19) Implement HF attenuation shelf selector (5/10/20 kHz)
**Done When:** Shelf rolloff corresponds to selected frequency.

### 20) Combine HF boost + HF attenuation simultaneously
**Done When:** Both can be applied without instability; response matches measurement expectations.

### 21) Add curve-evaluation function for UI overlay
**Goal:** A pure function that returns the predicted magnitude response for current EQP‑1A settings.  
**Done When:** Overlay curve matches measured curve within tolerance.

### 22) Add unit tests (C++ or script-level) for parameter mapping
**Goal:** Ensure ranges and enum selections cannot drift.  
**Done When:** Tests fail if enum values or max dB ranges change.

### 23) Add calibration constant(s) for dBFS ↔ dBu reference
**Goal:** Standardize a mapping used by distortion tests.  
**Done When:** Calibration is documented in MEASUREMENT_PLAN and reflected in tests.

### 24) Add output trim stage
**Done When:** Trim is smooth and does not clip at unity unless input clips.

### 25) Implement mono compatibility and channel linking
**Goal:** Ensure identical processing per channel; optional mid/side later.  
**Done When:** Left/right produce identical results given identical inputs.

### 26) Add CPU micro-benchmark harness mode (optional)
**Goal:** Quick perf check under multiple block sizes.  
**Done When:** Script prints ms/block and fails if above threshold.

---

## EPIC C — Analog/color stage (Tickets 27–35)

### 27) Add “analog enabled” toggle
**Done When:** With toggle off, plugin is linear (distortion tests show THD near noise floor).

### 28) Implement tube-style soft clipping (initial simple model)
**Done When:** No alias explosions; oversampling reduces alias products in tests.

### 29) Add drive control and calibration
**Done When:** Drive range is musically useful; documented in SPEC & measurement plan.

### 30) Add transformer-ish coloration (frequency-dependent saturation/tilt)
**Done When:** Subtle effect visible in harmonic spectra and frequency response (low-end).

### 31) Add optional analog noise (off by default)
**Done When:** Noise level is stable and can be targeted to spec in measurement tests.

### 32) Add anti-denormal handling inside nonlinear blocks
**Done When:** Stress test at silence shows stable CPU.

### 33) Add oversampling mode “Auto” (optional)
**Goal:** Automatically enable oversampling when analog stage enabled.  
**Done When:** Mode switch behavior documented and tested.

### 34) Add latency reporting + compensation tests
**Done When:** Harness auto-align residual is stable; reported latency matches measured.

### 35) Add a “safe mode” fallback for unsupported hosts
**Goal:** If oversampling init fails, fall back to Off without crashing.  
**Done When:** Simulated failure path does not crash.

---

## EPIC D — Modern EQ add-ons (Tickets 36–41)

### 36) Implement fixed 100 Hz HPF toggle
**Done When:** HPF response matches spec in measurement suite; bypass is bit-transparent.

### 37) Implement Param EQ band 1 (bell)
**Done When:** Frequency/gain/Q are stable and smooth; bypass nulls.

### 38) Implement Param EQ band 2 (bell)
**Done When:** Same as band 1.

### 39) Add routing option: add-ons pre/post Pultec (optional)
**Done When:** Routing is deterministic and saved in state; default is post.

### 40) Add per-band gain scaling/limits to prevent explosions
**Done When:** Extreme settings do not produce NaNs or clipping beyond expected.

### 41) Add UI affordances for add-ons (controls + bypass)
**Done When:** Controls are accessible and automation works.

---

## EPIC E — UI + analyzer (Tickets 42–48)

### 42) Build initial UI layout for ProgramEQ
**Goal:** Separate “Pultec section” and “Modern section”.  
**Done When:** All parameters are visible and controllable.

### 43) Implement analyzer FIFO + background FFT thread/timer
**Done When:** No audio-thread locks; analyzer can be enabled/disabled.

### 44) Add EQ curve overlay drawing
**Done When:** Curve matches measured response within tolerance.

### 45) Add bypass/compare UX
**Done When:** “EQ IN/OUT” and “True Bypass” are clearly different in UI.

### 46) Add parameter automation stress UI test case
**Goal:** Rapid automation ramps while rendering.  
**Done When:** No zipper or pops; measurement detects smoothness.

### 47) Add resizing + HiDPI handling
**Done When:** UI scales cleanly; analyzer remains performant.

### 48) Add “quality” settings panel
**Goal:** Oversampling, analyzer FFT size/speed, analog noise toggle.  
**Done When:** Settings persist and are host-automation-safe where appropriate.

---

## EPIC F — Fully automated measurement suite (Tickets 49–60)

### 49) Add Python measurement runner script
**Goal:** `python scripts/run_measurements.py --plugin <path>` orchestrates all tests.  
**Done When:** It builds a timestamped folder in `artifacts/` and writes summary JSON.

### 50) Add stimulus generator upgrades
**Goal:** Add sine, multi-sine, and log sweep generation (24-bit WAV).  
**Done When:** Deterministic outputs; matches MEASUREMENT_PLAN parameters.

### 51) Add frequency response analyzer (impulse FFT + sweep deconvolution)
**Done When:** Produces FR JSON/CSV and plots; tolerances enforced.

### 52) Add THD+N analyzer for sine tests
**Done When:** Outputs harmonic levels and THD; pass/fail thresholds implemented.

### 53) Add aliasing test (high-frequency tone + drive, compare oversampling modes)
**Done When:** Script computes “alias energy” metric; oversampling must improve it.

### 54) Add noise-floor test
**Done When:** Measures RMS noise in silence render; compares against target.

### 55) Add bypass semantics tests (EQ IN/OUT vs true bypass)
**Done When:** Null tests and coloration expectations are enforced.

### 56) Add param-band response tests (center freq, Q, gain grid)
**Done When:** Automated FR checks cover both param bands.

### 57) Add HPF response test (100 Hz)
**Done When:** Cutoff and slope verified; bypass nulls.

### 58) Add JSON case library in `tests/cases/`
**Done When:** Case files exist for all major measurement scenarios.

### 59) Add golden baseline mechanism
**Goal:** Save “golden” metrics per version; compare with tolerances.  
**Done When:** `--update-goldens` workflow exists and is documented.

### 60) Add CI integration (GitHub Actions or local CI)
**Goal:** Run smoke + subset of measurements on PR.  
**Done When:** CI fails on regression; artifacts uploaded on failure.

