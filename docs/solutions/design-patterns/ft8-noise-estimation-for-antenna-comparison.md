---
title: Signal and noise estimation for FT8-based antenna comparison
date: 2026-10-09
category: design-patterns
module: measurement engine (ΔS, ΔN)
problem_type: design_pattern
component: measurement
severity: high
applies_when:
  - "estimating noise (ΔN) to compare two antennas on an FT8 band"
  - "choosing the time window for noise measurement between FT8 cycles"
  - "considering a decoder's SNR (WSJT-X, weakmon) as the measurement"
tags: [ft8, snr, noise-floor, delta-s, delta-n, dt, weakmon, wsjt-x]
---

# Signal and noise estimation for FT8-based antenna comparison

## Context

reAPET compares antennas through the SNR difference between two receivers decoding the same FT8 stations. In 2019 Cogoni rejected the WSJT-X SNR and wrote a modified decoder (a weakmon fork) with an "absolute" SNR. Re-examining that work and the logs in the repository (`oldAPET/decoded_IS0KYB*.txt`, `oldAPET/decoded_IU3QEZA*.txt`) surfaced facts that cannot be read from the code and that decide how the estimator must be built. The full evidence, with numbers, is in `docs/review-2019.md` (item 2).

- **The modified decoder's per-spot ΔS is sound.** `snr_is0kyb` divides the tone power by the block's noise (`ft8.py:2846` in the `iu3qez/weakmon` fork, commit 8bd0184 of that repository), and the notebook multiplies the same noise back in, so the result is exactly the signal power. With matched chains, the ratio of the two receivers' signal powers is the relative gain, independent of the noise estimate.
- **The "background noise" is not noise.** `find_background` computes `rfft(samples, 1920)` (`ft8.py:2365`), which truncates the buffer to its first 1920 samples at 6000 Hz (`ft8.py:1769`). That is the first 0.32 s of the cycle, which starts at second 0 (`ft8.py:1824-1836`). It then takes the 10th percentile of the magnitude over 100–3000 Hz (`ft8.py:2380`). The source comment says "FFT magnitude for the whole signal", so measuring in the pause was accidental. In the IU3QEZA logs (urban site) the value swings by about 30–35 dB between the 5th and 95th percentiles and correlates positively with the number of decodes per block (+0.44 and +0.49). It grows with band activity, so it contains signals.
- **The real pause is not where the PC clock puts it.** The median spot DT is +0.28 s in the IU3QEZA logs and +0.59 s in IS0KYB1. An offset shared by every station comes from the receiver's clock or audio latency. The "obvious" end-of-cycle window, 13.3–15.3 s, overlaps 91–96% of decoded transmissions; the 0–0.32 s window only 5–6%; a 14.0–15.0 s window 6–15%.
- **Stations below the decode threshold contaminate the floor.** On a crowded band, undecodable FT8 signals form a continuous carpet that arrives from the antenna's directions. Measured inside the FT8 subband, that "noise" depends on the antenna pattern and is not ambient noise. DT cannot reveal it, because those stations are never decoded.

The WSJT-X SNR stays excluded as a measurement (boundary in `STRATEGY.md`): its noise estimate rises with band crowding.

## Guidance

1. **Separate ΔS and ΔN.** Compute ΔS per spot as the ratio of signal powers; it needs no noise estimate. ΔN is one value per time window. ΔSNR is their combination, ΔSNR = ΔS − ΔN, and is reported together with its two components, not instead of them.
2. **Place the noise window from the data, not from the clock.** The session's DT distribution shows where the real pause falls on the receive chain; choose the window least overlapped by mistimed stations.
3. **Make the estimate robust:** several windowed frames, a low percentile over time × frequency, averaging over several cycles.
4. **Invalidate rather than guess.** A cycle with no sufficiently clean window yields no ΔN. When too many cycles are invalidated, the session declares "ΔN not measurable" instead of reporting a number.
5. **Also measure outside the FT8 subband.** Separating ambient noise from the carpet of sub-threshold signals needs a quiet adjacent slice. This is why the recorder stores one next to the FT8 subband.
6. **Validate with the zero test:** the same antenna on both receivers through a splitter must give ΔS and ΔN centred on zero, including on a crowded band.

## Why This Matters

A ΔN computed by an estimator that contains signals shifts ΔSNR with band activity rather than with the antenna: a more directive antenna collects more signals from its good direction and appears "noisier". A window placed by the PC clock falls on top of transmissions, so the measured noise is really signal. Both errors are silent and produce plausible numbers. They are exactly the impressions dressed up as numbers that reAPET exists to eliminate.

## When to Apply

- When implementing or changing the ΔN estimate in the measurement engine.
- When choosing an FT8 decoder and deciding which quantities to take from it (signal level, DT).
- When interpreting a ΔSNR measured on a crowded band or at an urban site.

## Examples

Measuring how contaminated a candidate window is from a session's DTs, assuming DT is relative to the nominal 0.5 s start (a transmission spans 0.5 + DT to 13.14 + DT):

```python
dt = np.array([...])                     # DTs of the decoded spots in the session
def contaminated(w0, w1):                # window [w0, w1] in seconds of the cycle
    start, end = 0.5 + dt, 13.14 + dt
    # overlap with the current cycle or with the tail of the previous one
    return ((start < w1) & (end > w0)) | (end - 15.0 > w0)
print(contaminated(13.3, 15.3).mean())   # IU3QEZA logs: about 0.9
print(contaminated(0.0, 0.32).mean())    # IU3QEZA logs: about 0.06
```

## Related

- `docs/review-2019.md`, item 2: full evidence, tables and the analysis of the IU3QEZA session.
- `docs/plans/2026-10-09-1352-feat-dual-tuner-iq-recorder-plan.md`: R4 and KTD6 (quiet adjacent slice stored next to the FT8 subband).
- `STRATEGY.md`: the WSJT-X SNR boundary and the zero-test metric.
- `docs/solutions/tooling-decisions/rspduo-dual-tuner-sdrplay-api-not-soapysdrplay3.md`: the device backend that provides the sample counter and overload events.
