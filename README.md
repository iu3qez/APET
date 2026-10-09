# reAPET — APET Reborn

Experimental comparison of HF antennas, receive only.

A radio amateur who builds or modifies an antenna has no practical way today to know, from data rather than impressions, whether it really beats another one and in which directions. Comparing on transmit is complicated. WSPR gives few samples, RBN has no statistical base. An A/B switch compares different moments and mixes the antenna with changing fading, stations and QRM.

reAPET compares two antennas **at the same time**: each one is connected to one of the two receivers of the same SDR. For every FT8 station received by both, it measures:

- **ΔS**, the difference in signal level, i.e. the relative gain in the direction the station arrives from;
- **ΔN**, the difference in noise, estimated in the pauses between one FT8 cycle and the next.

The result is a dated measurement tied to its context: a relative-gain pattern where data exists, with coverage and reliability declared sector by sector, and its evolution over time. It is not "the pattern" of the antenna, which depends on propagation, time and place.

## Status

The project is restarting. The first component under development is a **dual-receiver IQ recorder**, to be tried in the field at the CQ WW DX CW contest on 28 November 2026. The recorder:

- drives an SDRplay RSPduo in dual-tuner mode through the official SDRplay API, on a Windows or macOS laptop;
- sets and locks equal gains on both tuners, with AGC off;
- marks saturation, overload and interruptions;
- stores data and context (antennas, locator, clock state) as SigMF, reanalysable offline.

The decoder, the ΔS and ΔN computation and the report come later, built on the recorded sessions.

## Documentation

- [`STRATEGY.md`](STRATEGY.md): purpose, positioning, boundaries and metrics.
- [`docs/review-2019.md`](docs/review-2019.md): critical review of the original work, with the checks run on the logs.
- [`docs/plans/`](docs/plans/): work plans. The recorder plan is tracked in issue [#1](https://github.com/iu3qez/reAPET/issues/1).
- [`docs/solutions/`](docs/solutions/): documented learnings (technical decisions and measurement patterns).
- [`CONCEPTS.md`](CONCEPTS.md): project vocabulary.

## The original work

reAPET restarts from **APET** (Antenna Pattern Extraction Tool) by Marco Cogoni IS0KYB, written in 2019 ([mcogoni/APET](https://github.com/mcogoni/APET)). The starting idea and the first implementation are his: two receive chains in parallel, first with WSPR and then with FT8, to derive an antenna's azimuth pattern against a reference and compare it with the NEC model. The draft of the article written for QEX and never published is in [`QEX_paper.pdf`](QEX_paper.pdf).

The original code is kept as it was, at the repository root:

- `WSPR_Antenna_Pattern.ipynb`: the notebook with all the processing;
- `coords_utils.py`: Maidenhead conversion and distance/azimuth computation;
- `decoded_*.txt`: example FT8 logs, from 2019 (IS0KYB) and 2025 (IU3QEZ);
- `LazyH-16m.csv`, `4cross_quads.csv`: patterns exported from MMANA;
- `pattern.png`, `DeltaSNR_time.png`: examples of the original results.

It has not been updated and does not run with current Python libraries. What holds up in that work and what does not is explained in the [review](docs/review-2019.md).

## License

GPL v3, like the original project. See [`LICENSE`](LICENSE).

73 de IU3QEZ
