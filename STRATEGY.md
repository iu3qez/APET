---
name: reAPET
last_updated: 2026-10-09
---

# reAPET Strategy

## Purpose

Radio amateurs have no practical way to compare two HF antennas experimentally, so judgement is left to impressions. Comparing on transmit is complicated, WSPR gives few samples, RBN has no statistical base, and an A/B switch compares different moments, mixing the antenna with changing fading, stations and QRM. What is missing is a simultaneous, receive-only measurement with a sufficient statistical base.

## Positioning

The rigour lives in the software, not in the operator: two matched receivers, even cheap ones, two antennas, and nothing else to do. reAPET measures ΔS (relative gain, spot by spot) and ΔN (noise, estimated in the pauses between FT8 cycles) separately, with its own decoder and an estimate that is declared and verifiable. The result is a dated measurement tied to its context, including its evolution over time, not "the pattern" of the antenna.

## Users

**Primary:** Homebrewer - has just built or modified an antenna and uses reAPET to learn, from data rather than impressions, whether and in which directions it beats their reference, with a result anyone can understand without explanation.

## Boundaries

- WSJT-X SNR is never a measurement source.
- No comparison between measurements from different hams or places (public archives, rankings): every measurement is relative to its own reference and context.
- No single number as the result, no spot density presented as a lobe, no sector interpolated without data; symmetry is only a teaching option, off by default.
- No procedures put on the operator (antenna swaps, mandatory calibration); the zero check with a splitter stays optional.
- Not yet: angle of arrival and propagation mechanism (phase 2); meanwhile the recorded data must make it possible.

_Resist a change when:_ it moves work or judgement from the software to the operator, or makes the result look more complete or more general than the session's data allows.

## Key metrics

- **Zero test (splitter)** - bias and spread of ΔS and ΔN with the same antenna on both receivers, including as a function of band crowding and signal level; the project's validation bench.
- **Internal consistency** - difference between the patterns from even and odd cycles of the same session; gives the minimum detectable difference, computed for every session.
- **Time and friction to first result** - from "I have two receivers" to the first report, measured with hams outside the project.
- **Readability** - a third party, looking only at the report, correctly answers "which antenna is better, towards where, when".

## Tracks

### Measurement engine with validation

Capture from two chains, FT8 decoder, ΔS per spot, ΔN in the pauses, zero test and internal consistency; it starts with no decoder.

_Why it serves the approach:_ this is where the measurement is won or lost: without a defensible SNR estimate, everything else is a chart on top of an impression.

### Zero friction

From installation to first result without the ham having to act like a lab technician.

_Why it serves the approach:_ objectivity depends on the operator intervening as little as possible.

### Readable report

ΔS pattern only where data exists, coverage and reliability declared per sector, evolution over time.

_Why it serves the approach:_ anyone must understand the result without confusing where stations come from with where the antenna has gain.

## Milestones

- **2026-11-28** - CQ WW DX CW: a field gathering to share the tool and train other hams, with up to one hour of test recording (magnetic loop against a real antenna).

## Brand

**One-liner:** APET Reborn
