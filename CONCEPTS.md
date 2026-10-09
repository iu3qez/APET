# Concepts

> Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Measurement

### ΔS

The difference in received signal level of the same station between the two antennas, measured spot by spot. It is the relative gain of the two antennas in the direction the station arrives from.

### ΔN

The difference in noise level between the two antennas over a time window, measured where no station transmits. It is reported alongside ΔS, never folded into it, because for receiving antennas the noise difference can matter as much as the gain difference.

### ΔSNR

The combination ΔS − ΔN: how much better one antenna receives a station than the other once both signal and noise are counted. Always reported with its two components.

### Zero test

Both receivers fed from the same antenna through a splitter. ΔS and ΔN must come out centred on zero; any bias or spread measures the error of the method itself.

## Recording

### Session

One recording of a two-antenna comparison: the IQ samples of both receivers plus their context (antennas, locator, read-back settings, clock state, events), stored together and reanalysable offline.

A session is never altered after it closes. Changing antennas, band or gain requires a new session.

### Dual tuner

The mode of an SDR in which two receivers of the same device sample simultaneously on one clock, each connected to one of the two antennas under comparison.

The two chains must be equivalent (same input type, same settings), and every parameter is set and read back for each receiver separately.

### Sample counter

The running number of the first sample of each block, provided by the device for each receiver. It is what pairs the blocks of the two receivers and measures lost samples exactly.

### Gap

An interval of missing samples on at least one receiver, detected from a sample counter discontinuity or a dropped block. Every gap is declared in the session, and the other receiver's samples over the same interval are dropped so that the two recordings stay aligned.

### Saturation

Clipping visible in the captured IQ samples: samples near full scale. It is detected from the data and declared as intervals per receiver.

### Overload

Front-end overload reported by the device itself. It can occur with no visible saturation in the IQ, for example from a strong signal outside the captured band.

## Flagged ambiguities

- "Saturation" and "overload" had been used as synonyms; they are distinct. Saturation is seen in the samples, overload is reported by the device.
