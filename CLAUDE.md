# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

All repository content is written in English: documentation, plans, learnings, code comments, commit messages, issues and pull requests. Conversation with the user may be in another language; what lands in the repository is English.

## What this repository is

**reAPET** ("APET Reborn"): a tool for comparing two HF antennas experimentally, using two receivers at the same time. It restarts from the work of Marco Cogoni IS0KYB (APET, 2019); since 2026 the repository is no longer a fork.

Read before any non-trivial work:
- `STRATEGY.md`: purpose, positioning, boundaries and metrics. The boundaries are binding (for example: WSJT-X SNR is never used as a measurement; no procedures are put on the operator; sectors without data are never interpolated).
- `docs/review-2019.md`: critical review of the original work, with checks run on the logs. It explains why the method measures ΔS and ΔN separately and why the noise window is placed from DT data.
- `docs/plans/`: work plans in the Compound Engineering format (`ce-unified-plan/v1`). The active plan is the dual-receiver IQ recorder (issue iu3qez/reAPET#1).

## State of the code

The recorder of the active plan is implemented in the Python package `reapet` (`src/reapet/`, tests in `tests/`), tested only against the simulated device; the hardware checks are listed in `docs/install.md`. Run `pytest` and `ruff check src tests` (a virtualenv with `pip install -e ".[dev]"`).

- `device.py`: device interface, capability check (R14), lock and per-tuner readback. `sdrplay.py`: SDRplay API 3.15 binding (`ctypes`), RSPduo dual tuner, 32-bit `firstSampleNum` unwrapped to 64 bits. `fake_device.py`: simulated device with injectable clipping, overload, counter gaps, disconnection.
- `acquisition.py`: callback ring buffer (`BlockQueue`) and the writer (`Recorder`): pairing by counter, gaps, saturation and overload intervals, disk checks. `dsp.py`: block statistics, hysteresis, polyphase decimator. `session.py`: SigMF Collection, journal, metadata built from the journal, `recover`.
- `context.py`: antennas, locator, SNTP. `gain.py`: headroom check. `bands.py`: tuner and narrow slice per band. `cli.py`: `doctor`, `record`, `recover`.

Positions in the journal are wide-band counter values; they are mapped to recording sample indices only when the metadata is built.

**Legacy code (`oldAPET/`), do not modify:**
- `WSPR_Antenna_Pattern.ipynb` is the real code: every function is defined in cell 1, and cell 2 loads the data (`mode = "FT8"` or `"WSPR"`; reporters, locator and time window are hard-coded in the cell).
- `wspr_utils.py` is a diverging, unused copy of cell 1 (its import is commented out).
- `coords_utils.py`: Maidenhead locator ↔ lat/lon and `haversine` (distance, azimuth). This is the reusable part.
- `spot_processing.py`, `cty.py`, `cty.plist`: taken from DH1TW's DX-Cluster-Parser, effectively unused.
- `decoded_<REPORTER>.txt`: FT8 logs from the modified weakmon decoder. Each block starts with `------ TIME: <unix>, Background noise: <power> ------`, followed by 10-field lines: `P<pass> <band> <second> <Hz> <start> <DT> <snr> <msg...>`. The "background noise" contains signals too (see the review): do not use it as noise.
- `LazyH-16m.csv`, `4cross_quads.csv`: 3D patterns exported from MMANA (`ZENITH,AZIMUTH,VERT,HORI,TOTAL`).

The notebook does not run with the versions in `oldAPET/requirements.txt` (numpy 2: `np.linspace` with a float `num` in `regularize_data`; `%pylab` is deprecated), and it uses local time (`fromtimestamp`, `mktime`) although its comments say UTC. Cogoni's weakmon fork is not to be used as a base for anything.

## Agreed technical direction (recorder)

Details and rationale are in the plan under `docs/plans/`. In short:
- Python 3.12/3.13 package with a `src/reapet/` layout and the commands `reapet doctor`, `record`, `recover`; tests with pytest, lint with ruff.
- In the field: an RSPduo in dual-tuner mode on a Windows or macOS laptop, driven through the **SDRplay API directly** (`ctypes` binding). Do **not** use the SoapySDRPlay3 driver for the RSPduo: in dual-tuner mode it ignores the channel index for gain/AGC/frequency, never realigns the channels, and drops `firstSampleNum` and overload events. SoapySDR remains the path for other devices (Orion MkII, TRX DUO via openHPSDR).
- The two channels are aligned by sample counter (`firstSampleNum`); a gap on one tuner opens a new segment on both recordings.
- Sessions are stored as SigMF: one Collection with one recording per antenna, native `ci16_le` data, context under the `reapet:` namespace, an append-only journal for crash safety.
- Capture wide (~2 MS/s) to see saturation, store narrow (FT8 subband plus an adjacent quiet slice).

## Compound Engineering artifacts

Config is in `.compound-engineering/config.yaml` (everything commented out); the artifact root is `docs/` (plans in `docs/plans/`). The scratch space `.context/compound-engineering/` is in `.gitignore`.

`docs/solutions/` holds documented learnings (technical decisions, measurement patterns), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`); relevant when implementing or debugging in a documented area. Project vocabulary is in `CONCEPTS.md`.

## How to work

Write every report, summary, or handoff to the user through the `ce-noslop` skill. This applies when you are the top-level agent writing to the user, not when you are a subagent reporting to its caller. Do not apply it to code, config, verbatim quotes, or text the user asked to post as written.
