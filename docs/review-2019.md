# Critical review of APET (2019)

Review of the assumptions and claims in the original work by Marco Cogoni IS0KYB (`QEX_paper.pdf`, `WSPR_Antenna_Pattern.ipynb`, example FT8 logs), as the basis for reAPET. See `STRATEGY.md` for the choices that follow from it.

Status: **Refuted** (contradicted by data or by calculation), **To fix** (right in principle, wrong in execution), **To verify** (plausible but not demonstrated), **Confirmed**.

## Method

### 1. Averaging over polarization — Refuted

Article: the 2 minutes of WSPR cover "roughly one full polarization rotation", citing Epstein (1969): 0.25 turns/min by day, almost zero at night.

0.25 turns/min × 2 min = **0.5 turns**, not one. With FT8 (12.64 s) it comes to about 0.05 turns: a single spot averages nothing. Averaging over polarization happens only **across different spots**, so it depends on the number of spots per sector, not on the length of the mode. At night, with almost no rotation, comparing antennas of different polarization (vertical loop vs horizontal Lazy H) stays systematically biased.

**reAPET:** reliability per sector must come from the number of independent spots and from internal consistency, not from an assumption of averaging within a spot.

### 2. The modified decoder's "real SNR" — To fix

Code (`extract_ft8_data`): `snr = snr_weakmon + 10·log10(background_noise)`, then `get_deltasnr_bycall` subtracts each receiver's session median noise. The result is ΔS (per spot) − ΔN (session median). The idea is close to the ΔS/ΔN separation adopted by reAPET, but:

- **Verified in the weakmon fork** (`iu3qez/weakmon`, `ft8.py`, Cogoni commits of 2019-05-07/11): `snr_is0kyb` = 10·log10(mean of the squares of the strongest tone per symbol / `noise_power`), with `noise_power` taken from the same block. So `snr + 10·log10(noise)` reconstructs the signal power **exactly**: the per-spot ΔS does not depend on the noise estimate. The `rawsnr < 0.1` floor never triggers in the logs in the repository (0 spots ≤ −10 dB).
- **Where the noise is measured** (`find_background`): `rfft(samples, 1920)` truncates the buffer to its first 1920 samples at 6000 Hz, i.e. **the first 0.32 s of the cycle**, before the nominal start of transmissions (0.5 s). It takes the 10th percentile of the magnitude over 100–3000 Hz, with no windowing, a single snapshot per cycle and no averaging across cycles. The source comment says "FFT magnitude for the whole signal", so measuring in the pause was almost certainly accidental. Measuring noise in the pauses was therefore already done in practice, but without the safeguards it needs (see below).
- The "background noise" does not behave like noise. Measured on the logs in the repository (p5–p95 in relative dB):

  | Log | blocks | p5 | median | p95 | spread |
  |---|---|---|---|---|---|
  | IS0KYB1 (Kiwi) | 1056 | 35.6 | 37.2 | 40.2 | 4.6 dB |
  | IS0KYB2 | 529 | 42.3 | 46.1 | 52.7 | 10.4 dB |
  | IU3QEZA1 | 438 | 25.1 | 46.4 | 60.5 | **35.4 dB** |
  | IU3QEZA2 | 426 | 25.3 | 44.1 | 54.6 | **29.3 dB** |

  Swings of 30 dB within tens of seconds are not external noise. Analysis of the IU3QEZA session (2025-01-03, 10:53–13:02 UTC, urban site):
  - per-block correlation between "noise" and number of decodes: **+0.44 / +0.49**. The estimate grows with band activity, so it **contains signals**;
  - correlation of the "noise" between the two receivers: +0.73, consistent with a common cause (the band);
  - no signature of a local transmitter (high noise with collapsed decodes). On RX1 there are peaks synchronous with the FT8 cycles (:28/:58) with normal decodes: possibly a strong nearby FT8 station;
  - after a pause of about 20 minutes (11:30–11:40) on both receivers, RX2 drops by ~12 dB and RX1 does not: a level step in chain 2, probably an operator action;
  - after 12:50 the decodes drop to zero and the "noise" collapses: end of the session.

  With the measurement already in the pause, the positive correlation with decodes points to **contamination of the 0–0.32 s window**: stations with negative DT, tails of the previous cycle, a misaligned PC clock (the window position depends on system time). A single 0.32 s snapshot is also exposed to impulsive noise.

  Used as N, it falsifies ΔN. The mid-session step shows that the offset between chains can change without anyone noticing: the measurement engine must detect it and split the session.
- ΔN is never reported: for receiving antennas (low bands) it is half of the result.

Contamination of the pause by mistimed stations, measured from the DT of decoded spots (`dec.dt`, assumed relative to the nominal 0.5 s start): percentage of spots whose transmission overlaps the window.

| Log | DT p5 / median / p95 | 0–0.32 s (Cogoni) | 13.3–15.3 s | 14.0–15.0 s |
|---|---|---|---|---|
| IS0KYB1 | −0.01 / +0.59 / +1.32 s | 5% | 96% | 15% |
| IU3QEZA1 | −0.29 / +0.28 / +0.64 s | 6% | 91% | 6% |
| IU3QEZA2 | −0.31 / +0.28 / +0.64 s | 6% | 92% | 6% |

A non-zero median DT is an offset shared by all stations, so it belongs to the receiver's clock or audio latency: the real pause is not where the PC clock puts it. Sub-threshold signals, which DT cannot reveal, form on a crowded band a carpet that arrives from the antenna's directions. This is the likely main cause of the correlation between "noise" and decodes, and the reason why ΔN inside the FT8 subband may not be ambient noise. To be checked with the zero test and with a measurement in an adjacent quiet slice.

**reAPET:** ΔS from the ratio of signal levels (matched chains): Cogoni's method is sound and can be kept. ΔN in the pauses between FT8 cycles, with the safeguards that were missing: a window placed from the data (the session's DT distribution, choosing the least contaminated window), several windowed frames, a percentile over time × frequency, averaging over several cycles and validation with the zero test. A cycle with no sufficiently clean window yields no ΔN; if too many cycles are invalidated, the report declares "ΔN not measurable in this session" instead of giving a number. ΔS and ΔN are reported separately.

### 3. "Quasi-omnidirectional" reference — Not verifiable, superseded

Article: the LZ1AQ loop is "quasi omnidirectional on 14 MHz for elevation angles above 1-2 degrees". A single vertical loop has a figure-of-eight azimuth pattern with deep nulls; it is omnidirectional only as crossed loops combined in quadrature. The configuration used is not stated. Fig. 2 also shows the loop stops receiving at night: the reference has an elevation response very different from the antenna under test, so ΔS mixes the azimuth and elevation of both.

The configuration cannot be reconstructed (the author does not reply). The IU3QEZA measurements use a resonant vertical: omnidirectional in azimuth in the model, but in an urban garden the radials, ground, nearby buildings and common-mode currents on the feed line make it less omnidirectional than expected. It is also vertically polarized with a null at the zenith, so on short paths with high angles it penalizes the reference. Finally it picks up more local noise, which weighs on ΔN.

**reAPET:** the reference is part of the measurement; the report declares it rather than assuming it neutral.

### 4. WSJT-X SNR unreliable — Confirmed (reasoning to verify)

The WSJT-X noise estimate rises with band crowding, so a signal's SNR depends on the other signals present. The reason given in the README ("depends even on the window size in pixels") is not documented and probably refers to the decoding window in frequency, not to pixels. Irrelevant for reAPET: WSJT-X is excluded as a source (see `STRATEGY.md`).

### 5. Offset between receive chains — Confirmed, minor weight

Measured 3 dB (Kiwi vs TS-940S) and 1 dB (Kiwi vs Perseus). With matched chains and a ΔS spread of several dB, 1–2 dB is within measurement noise. The zero check with a splitter stays optional, but it is also the validation test of the estimator (bias as a function of crowding and level).

## Analysis and presentation

### 6. Symmetry + cubic interpolation — Refuted as a general method

Every point is duplicated at az+π and counted as independent; `regularize_data` fills empty bins with the mean of their neighbours and `interp1d(..., fill_value='extrapolate')` extrapolates. In the published case the South (Africa, almost no spots) is drawn with other directions' data. Symmetry requires a symmetric antenna, environment and reference: in HF almost never.

**reAPET:** sectors without data stay empty; symmetry only as a teaching option, off by default.

### 7. Spot density read as a lobe — Untreated risk

The number of spots per direction reflects where hams are and where the skip lands, not the gain. The 2019 polar plots overlay points and curve without separating density from ΔS.

**reAPET:** the pattern shows only ΔS; coverage is separate information.

### 8. "Within 3 dB of the predicted" (Fig. 6) — To verify, probably optimistic

Comparison with the difference of two MMANA models at 4 elevations (5–35°) chosen after the fact, on data doubled by symmetry and interpolated, with no stated uncertainty. With 4 theoretical curves available, one is likely to fall within 3 dB. NEC models do not see the real ground, which is precisely the stated motivation for the method.

### 9. Weights and medians — Article/code mismatch

The article says median per station, with the standard deviation used as a weight for interpolation. The code (commit `ca984bc`, "abandon medians use all values") uses all values, without weights.

### 10. Choice of the time window — Researcher degrees of freedom

"Avoid periods with a steep slope", choosing the window by eye on the plot. The result depends on an unrecorded manual choice.

**reAPET:** the window is chosen by a declared criterion, or the report shows the evolution over time instead of a single pattern.

## Code defects (relevant only for reuse)

- `extract_ft8_data`: `locator` is not reset when a line carries no grid. The call inherits the previous line's locator, hence a wrong azimuth. `out.string` instead of `out.group(0)`.
- Timestamps in local time (`fromtimestamp`, `mktime`) although the comments say "UTC": correct only on machines running in UTC (Colab).
- `extract_info`: `dist_dict` is overwritten for every reporter.
- `regularize_data`: `np.linspace` with a float `num`, which fails with numpy ≥ 1.18.
- `%pylab inline` is deprecated; the notebook depends on its global namespace.
- `wspr_utils.py` is a diverging, unused copy of the notebook's cell 1.
- WSPR source (`wsprnet.org/olddb`, HTML scraping) presumably no longer available.

Verified and **not** a problem: pairing spots between the two receivers by exact second. With a ±7 s tolerance the number of pairs does not change (IU3QEZA: 1498 in both cases).

## Open items

1. ~~Read Cogoni's weakmon fork~~: done (item 2).
2. ~~Configuration of the LZ1AQ loop~~: cannot be reconstructed, item superseded (item 3).
3. ~~Explain the 30 dB noise swing in the IU3QEZA logs~~: mostly the estimator, which includes signals (see item 2). The −12 dB step on RX2 after 11:40 cannot be reconstructed: nobody remembers the action. Lesson: the software records the session context by itself (per-chain levels, interruptions, detected steps).
