# Case Library

This folder contains baseline JSON render cases for the currently implemented DSP scope, plus a few harness support cases used by existing scripts.

`pultec.lf_freq_hz` is a 4-choice parameter with normalized values mapped by choice index over `count - 1`:

- `20 Hz` -> `0 / 3 = 0.0`
- `30 Hz` -> `1 / 3 = 0.3333333`
- `60 Hz` -> `2 / 3 = 0.6666667`
- `100 Hz` -> `3 / 3 = 1.0`

Baseline library cases are listed in `case_manifest.json`.
