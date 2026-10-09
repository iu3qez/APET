# Installing and running the reAPET recorder

The recorder captures an SDRplay RSPduo in dual-tuner mode, one antenna per tuner, and stores each session as a SigMF Collection. The plan behind it is `docs/plans/2026-10-09-1352-feat-dual-tuner-iq-recorder-plan.md` (issue iu3qez/reAPET#1).

## Requirements

- Python 3.12 or 3.13.
- SDRplay API **3.15**, installed with the official installer from <https://www.sdrplay.com/api/> (Windows, macOS ARM and Intel, Linux). The installer puts in place both the library and the API service. Other API versions are refused, because the `ctypes` structures are written for 3.15.
- Nothing else: no SoapySDR, no compiler. The reasons are in `docs/solutions/tooling-decisions/rspduo-dual-tuner-sdrplay-api-not-soapysdrplay3.md`.

The library is looked up in the standard places (`C:\Program Files\SDRplay\API\x64\sdrplay_api.dll` or the folder in the registry on Windows, `/usr/local/lib/libsdrplay_api.so.3` on macOS and Linux). To use another file, set `REAPET_SDRPLAY_API` to its full path.

## Installation

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
reapet doctor
```

## Commands

`reapet doctor [--seconds N] [--band 20m]`
: Reports the API version, the devices found, the RSPduo modes available and the capabilities. It then receives for N seconds on both tuners (default 5) and reports per tuner the blocks, samples, measured rate, counter gaps and resets, overload events, dropped blocks and the counter step, followed by the A/B cross-correlation lag of the samples aligned by counter. It ends with "Suitable for recording" or with the reason it is not.

`reapet record --band 20m [--out sessions] [--duration S] [--store-wide]`
: Checks the device, asks for the two antenna names and the locator (an empty answer is recorded as missing), queries the clock by SNTP, runs the headroom check, locks the settings and records until Ctrl-C, `--duration`, a disconnection or the disk margin. `--antenna-a`, `--antenna-b` and `--locator` answer the questions in advance. `--store-wide` also stores the 2 MS/s band of each tuner (about 58 GB per hour for the two tuners). `--no-sntp` skips the time servers.

`reapet recover SESSION_FOLDER`
: Rebuilds a session left open by a crash or a killed process: it truncates the data to whole samples and equal lengths, rebuilds the metadata from the journal and marks the close as abnormal.

Every command accepts `--fake` to use the simulated device instead of the RSPduo, for example `reapet record --fake --duration 30`.

## What is recorded

| File | Content |
|---|---|
| `session.sigmf-collection` | The Collection: the two recordings and their metadata hashes |
| `rx-A.sigmf-data`, `rx-B.sigmf-data` | Narrow slice per tuner: 62.5 kS/s, `cf32_le`, full scale 1.0, about 1.8 GB per hour per tuner |
| `rx-A-wide.sigmf-data`, `rx-B-wide.sigmf-data` | With `--store-wide` only: 2 MS/s, `ci16_le` as delivered by the API |
| `rx-*.sigmf-meta` | SigMF metadata: one capture per segment, annotations for saturation, overload, gaps and session end, context under `reapet:` |
| `journal.jsonl` | Append-only event journal; the metadata is always rebuilt from it |
| `blocks.bin` | One row per received block and tuner: counter, PC time, peak, power, clipped samples (`reapet:block_table` gives the dtype) |

The narrow slice is stored as `cf32_le` rather than in the native `ci16_le`: after decimation by 32 the noise is about 15 dB lower than in the wide band, and with a high gain reduction it would fall to about one LSB of a 16-bit integer. The wide band keeps the native format. Where each slice sits on each band is in `src/reapet/bands.py`; the "quiet" slices next to FT8 are nominal and have to be checked against real recordings.

## Hardware checks still to do

The software has been tested only against the simulated device. These checks need the RSPduo; record the results here.

| Check | How | Result |
|---|---|---|
| U1. `doctor` runs and reports "Suitable" | `reapet doctor` on the macOS laptop (Windows if macOS fails) | pending |
| U1. A and B counters match | Same signal on both inputs through a splitter, `reapet doctor --seconds 10`: equal first counters, cross-correlation lag 0 and coefficient close to 1 | pending |
| U1. Python callbacks keep up | `reapet doctor --seconds 600`: no counter gaps, no dropped blocks, rate 2.0000 MS/s per tuner. If not: drop to a C module or to 1 MS/s (KTD14) | pending |
| U1. Counter step | `doctor` prints `counter_step`: samples per counter unit (1 if the counter runs at the output rate, 3 if at the 6 MHz ADC rate) | pending |
| U1. Spectrum orientation | A carrier at a known frequency inside the slice (signal generator or beacon) must appear at the expected offset in `rx-A.sigmf-data`; if it appears mirrored, I and Q are swapped | pending |
| U2. B follows A | Splitter, change the gain reduction: B levels follow A within a tolerance to record here | pending |
| U4. Saturation and overload | Strong in-band signal through an attenuator on one tuner opens a saturation or overload interval; tune the 98% threshold (KTD7) on the peak at the onset of overload | pending |
| U6. Gain thresholds | Note the gain chosen on a quiet band and on a busy one; tune the 10 dB margin | pending |
| U7. Endurance | One hour of recording on the chosen laptop; session valid, gaps counted, CPU load noted | pending |
| Recovery | Kill the process during a recording (`kill -9`, or Task Manager), then `reapet recover` | pending |

On this development container the writer processes about 2.5 times real time on two tuners with 2048-sample blocks (2.4 times with 512-sample blocks), measured under a profiler. The real block size of the API in dual-tuner mode is not known yet; it is the samples divided by the blocks that `doctor` prints.

## Field checklist (CQ WW, 2026-11-28)

- Laptop charged plus power bank or car inverter; disable sleep and screen lock for the duration.
- RSPduo on a short USB cable directly to the laptop, no hub.
- Both antennas on the **50 Ω** inputs (Tuner 1 and Tuner 2), never the Hi-Z input: the two chains must be equal.
- Input protection on both inputs (limiter or attenuator) and as much distance as possible from the contest stations' antennas.
- At least 10 GB free on disk for one hour of narrow storage (the recorder stops cleanly below the larger of 1 GB and 2 minutes of data).
- Before leaving home: `reapet doctor` with the antennas connected.
- In the field: `reapet record --band 20m`, enter the two antenna names and the locator, check that the status line shows `REC` and that the peaks look plausible, then leave it.
- At the end: Ctrl-C, check the line `Session closed (stop)`, copy the session folder to a second disk.
