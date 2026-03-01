# ProgramEQ — SPEC

This document is the **non‑drift specification** and acceptance contract for ProgramEQ.

## 1. Product definition

**ProgramEQ** is a VST3 equalizer plugin consisting of:

1) A **faithful digital reproduction** of the *Pultec EQP‑1A Program Equalizer* behavior (passive EQ network + makeup amp coloration and its bypass semantics).  
2) Two additional **fully parametric bell EQ bands** (modern utility).  
3) A toggleable **100 Hz high‑pass filter (HPF)**.  
4) A **real‑time spectrum/graph display** (FFT analyzer) and an **EQ curve overlay**.

ProgramEQ is built in this repo as a JUCE + CMake plugin target, with an optional CLI test tool:
- `BUILD_VST3_HARNESS` is ON by default and builds `tools/vst3_harness` (see root `CMakeLists.txt`).

## 2. Scope and constraints

### 2.1 Host formats (initial scope)
- **VST3** is required.
- Standalone build may exist but must not be used as a substitute for VST3 validation.

### 2.2 Threading rules
- **Audio thread** must not allocate, lock, or perform filesystem/network IO.
- Analyzer/UI must use lock‑free FIFO/ring buffer or equivalent.

### 2.3 Determinism
- DSP output must be deterministic across buffer sizes and host block boundaries
  (within floating point rounding).

## 3. Non‑drift requirements (stop‑the‑line rules)

If any requirement in this section is violated, the change is rejected.

### 3.1 EQP‑1A control points and ranges (must match hardware spec)

The EQP‑1A section must implement these exact frequency selections and ranges:

**Low shelf frequency selector (LF FREQ):**
- 20, 30, 60, 100 Hz

**Low shelf BOOST amount:**
- 0 … 13.5 dB (max)

**Low shelf ATTEN amount:**
- 0 … 17.5 dB (max)

**High peak BOOST frequency selector (HF FREQ):**
- 3, 4, 5, 8, 10, 12, 16 kHz

**High peak BOOST amount:**
- 0 … 18 dB (max)

**High shelf ATTEN selector (ATTEN SEL):**
- 5, 10, 20 kHz

**High shelf ATTEN amount:**
- 0 … 16 dB (max)

### 3.2 EQP‑1A bypass semantics
ProgramEQ must expose *two* distinct bypass concepts:

1) **Pultec “EQ IN/OUT”**: disables ONLY the EQ shaping; **the amplifier/color path remains in circuit**.  
2) **True Bypass**: disables all DSP and is effectively transparent (null testable).

### 3.3 “Pultec trick” low band interaction
When LF BOOST and LF ATTEN are both non‑zero, the resulting curve must exhibit the characteristic
interactive shape (boost + resonant dip) and must not behave as a simple cancellation.

### 3.4 Knob feel / tapers
Knob mapping for the EQP‑1A section must follow documented pot tapers for authentic automation feel.
(Implementation may be a digital mapping curve, not necessarily a literal pot simulation.)

### 3.5 Modern add‑ons must not contaminate the Pultec path
- The **two param bands** and **100 Hz HPF** must be **bit‑transparent when disabled**.
- The analyzer must not affect audio output or stability.

## 4. DSP architecture (required)

Signal flow (conceptual):

`Input → (optional) Analog Input Color → EQP‑1A Passive Network → Makeup Amp/Transformer Color → HPF (100 Hz) → Param Band 1 → Param Band 2 → Output Trim → Output`

Required properties:
- The EQP‑1A passive network must be implemented as a self‑contained module with a “flat” state.
- Any nonlinear/color stage must support internal oversampling modes.

## 5. Parameters (required)

### 5.1 Naming conventions (non‑drift)
- All parameters must have stable IDs suitable for automation and preset compatibility.
- Parameter IDs should be dot‑namespaced.

### 5.2 Minimum parameter set

**Global**
- `global.true_bypass` (bool)
- `global.output_trim_db` (float, e.g., −24 … +24 dB)
- `global.oversampling_mode` (enum: Off, 2x, 4x)
- `global.ui_analyzer_enabled` (bool; must not affect audio)

**EQP‑1A section**
- `pultec.eq_in` (bool)  // not the same as true bypass
- `pultec.lf_freq_hz` (enum: 20, 30, 60, 100)
- `pultec.lf_boost_db` (0 … 13.5)
- `pultec.lf_atten_db` (0 … 17.5)
- `pultec.hf_boost_freq_khz` (enum: 3, 4, 5, 8, 10, 12, 16)
- `pultec.hf_boost_db` (0 … 18)
- `pultec.hf_bandwidth` (continuous “sharp ↔ broad”)
- `pultec.hf_atten_sel_khz` (enum: 5, 10, 20)
- `pultec.hf_atten_db` (0 … 16)
- `pultec.analog_enabled` (bool) // color stage on/off
- `pultec.drive` (float; calibrated)

**Modern section**
- `hpf100.enabled` (bool)

Param band 1 (bell):
- `peq1.enabled` (bool)
- `peq1.freq_hz` (20 … 20000)
- `peq1.gain_db` (e.g., −18 … +18)
- `peq1.q` (e.g., 0.2 … 10)

Param band 2 (bell):
- `peq2.enabled` (bool)
- `peq2.freq_hz` (20 … 20000)
- `peq2.gain_db` (e.g., −18 … +18)
- `peq2.q` (e.g., 0.2 … 10)

## 6. Performance and quality bars

### 6.1 CPU targets (guidance)
- Oversampling Off: “lightweight” suitable for many instances.
- Oversampling 4x: allowed to be heavier but must not glitch on typical modern CPUs.

### 6.2 Stability
- No denormals.
- No NaNs/Infs.
- No audible zipper noise (parameter smoothing required).

## 7. Acceptance tests (must be automated)

All acceptance tests must be runnable via scripts (PowerShell + Python) and must be suitable for CI.

### 7.1 Build + smoke test (existing harness pipeline)
- Configure + build Release
- Build `vst3_harness`
- Render impulse through plugin
- Run `vst3_harness analyze --auto-align --null`

### 7.2 Null transparency tests
- **True bypass** must null within **−120 dBFS RMS** (after auto‑align).
- **Modern add‑ons OFF** must be bit‑transparent (null within −120 dBFS RMS) against a build with those modules removed/disabled.

### 7.3 Frequency response fidelity tests (EQP‑1A section)
- With `pultec.analog_enabled = false`, measure EQ curves and verify:
  - Control ranges and switch points are correct.
  - LF Boost+Atten interaction produces expected curve family.
  - HF boost bandwidth affects curve width correctly.
- Exact measurement method, sweeps, and tolerances are defined in `MEASUREMENT_PLAN.md`.

### 7.4 Distortion/noise behavior tests (color stage)
- With `pultec.analog_enabled = true`, measure THD and noise against targets defined in `MEASUREMENT_PLAN.md`.
- Oversampling modes must demonstrate reduced aliasing when drive increases.

### 7.5 Bypass semantics test
- `pultec.eq_in = false` must remove EQ shaping but preserve coloration when analog is enabled.
- `global.true_bypass = true` must remove coloration and EQ.

### 7.6 Regression gate
A PR is eligible to merge only if:
- Smoke + null tests pass.
- Measurement suite passes.
- No new parameters are renamed/removed without a migration plan.

## 8. Definition of “DONE”
ProgramEQ is considered feature‑complete when:
- All non‑drift requirements are satisfied.
- All acceptance tests pass on at least Windows (Release) and one additional platform if supported.
- The measurement suite is stable enough that changes in DSP are detectable and reviewable
  (i.e., meaningful diffs, not flaky noise).
