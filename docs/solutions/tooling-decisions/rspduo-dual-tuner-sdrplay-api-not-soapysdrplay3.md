---
title: RSPduo dual-tuner access through the SDRplay API, not SoapySDRPlay3
date: 2026-10-09
category: tooling-decisions
module: IQ recorder (device backend)
problem_type: tooling_decision
component: tooling
severity: high
applies_when:
  - "accessing an SDRplay RSPduo in dual-tuner mode"
  - "two channels must stay sample-aligned with per-tuner gain control"
  - "considering replacing the SDRplay backend with SoapySDR for uniformity"
retire_when: "SoapySDRPlay3 (github.com/pothosware/SoapySDRPlay3) routes the channel index to rxChannelB in dual-tuner mode, exposes firstSampleNum (as timeNs or a counter) and exposes overload events; check Settings.cpp (chParams assignments) and Streaming.cpp (rx_callback, PowerOverloadChange handling) in the latest release"
tags: [rspduo, sdrplay, soapysdr, dual-tuner, overload, sample-alignment]
---

# RSPduo dual-tuner access through the SDRplay API, not SoapySDRPlay3

## Context

The reAPET recorder captures two antennas with an RSPduo in dual-tuner mode. The two channels must stay sample-aligned, both tuners must run with equal locked gain, and saturation must be declared (R1, R2 and R9 in `docs/plans/2026-10-09-1352-feat-dual-tuner-iq-recorder-plan.md`). The first design accessed the hardware through SoapySDR, to get one interface for many SDRs.

The plan's feasibility review, followed by a reading of the SoapySDRPlay3 driver source (commit 48bd8b4 of the SoapySDRPlay3 repository, 2026-09-04, the latest at that date), showed that in dual-tuner mode the driver meets none of the three requirements:

- **Per-channel parameters are ignored.** The driver keeps a single channel-parameter pointer, `chParams`. It points to `deviceParams->rxChannelB` only when the selected tuner is B, and to `rxChannelA` otherwise (`Settings.cpp:2179`, and the same assignment at `Settings.cpp:400-401`). `setGainMode` and `setGain` write through `chParams` without using their `channel` argument (`Settings.cpp:553-565`, and `setGain` from `Settings.cpp:575`); `getGain` and `getGainMode` read through the same pointer. Setting or reading gain and AGC "on channel 1" therefore acts on whichever tuner `chParams` points to. A readback can report "equal gains, AGC off" while tuner B is in a different state.
- **Channels are never realigned.** `deactivateStream` does nothing (`Streaming.cpp:385-394`). On an already active stream, `activateStream` only sets a per-stream reset flag, clears the element count, registers the stream and returns (`Streaming.cpp:340-348`). Each channel then empties its own buffer when its own reader calls `readStream` (`Streaming.cpp:505-508`), so the two channels restart at different positions. The `firstSampleNum` counter is never read anywhere in the driver, and the driver never sets `timeNs`. The misalignment cannot be detected.
- **Overload is dropped.** The `sdrplay_api_PowerOverloadChange` event is acknowledged to the API and then ignored (`Streaming.cpp:173-186`). Front-end overload, which does not always produce full-scale samples in the decimated IQ, stays invisible.

On top of this, no current SoapySDRPlay3 module packages exist for Windows or macOS. The module must be built against the same SoapySDR library that Python loads.

## Guidance

Access the RSPduo in dual-tuner mode through the **SDRplay API v3 directly**, with a `ctypes` binding, behind the reAPET device interface. SoapySDR remains the path for devices that are not SDRplay.

- Set and read back every parameter on the structure of the matching tuner (`rxChannelA`, `rxChannelB`), never through a single shared pointer.
- Pair the blocks of the two tuners by `firstSampleNum`. A counter discontinuity on one tuner is a gap of exact length. Drop the other tuner's samples over the same interval and open a new segment on both recordings.
- Record `PowerOverloadChange` events per tuner, acknowledging them to the API, as a second saturation source next to the clipping visible in the IQ.
- Install the API with the official SDRplay installer (Windows, macOS ARM and Intel, Linux). Nothing has to be compiled.

## Why This Matters

With SoapySDRPlay3 the recorder would produce sessions that look correct and are not: "equal" gains that describe one tuner only, "aligned" channels that are offset by an unknown number of samples after every overflow, and no trace of overload. This is the same kind of silent error that invalidated the 2019 measurements (the −12 dB step on one chain described in `docs/review-2019.md`). An antenna comparison built on misaligned channels or different gains is wrong, and nothing reports it.

The temptation to return to SoapySDR for uniformity is real, because the interface is convenient and covers many SDRs. The SDRplay backend code alone does not explain why that was not done.

## When to Apply

- Whenever the RSPduo device backend is changed or a replacement is considered.
- When another multi-receiver SDR is added through SoapySDR. Before trusting the interface, check in the driver source that the channel index is honoured, that a counter or timestamp exists to align channels, and that overload is exposed.

## Examples

Quick check of a SoapySDR driver's source before adopting it for two coherent channels (indicative commands, run in a clone of the driver):

```bash
grep -n "chParams\s*=" Settings.cpp          # one pointer shared by all channels?
grep -rn "firstSampleNum\|HAS_TIME" .        # counter or timestamp exposed?
grep -n "Overload" Streaming.cpp             # overload forwarded or dropped?
grep -n "deactivateStream" -A10 Streaming.cpp
```

A driver that ignores the channel, exposes no counter or drops overload is not suitable for antenna comparison.

## Related

- `docs/plans/2026-10-09-1352-feat-dual-tuner-iq-recorder-plan.md`: Key Decision "RSPduo through the SDRplay API" and KTD5, KTD7, KTD14.
- Issue iu3qez/reAPET#1 (dual-receiver IQ recorder).
- `docs/solutions/design-patterns/ft8-noise-estimation-for-antenna-comparison.md`: why both overload and IQ saturation are recorded.
