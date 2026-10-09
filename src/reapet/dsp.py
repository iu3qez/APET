"""Signal processing for the recorder: block statistics, saturation intervals, decimation.

Sample positions are always wide-band counter values (the device sample counter,
unwrapped to 64 bits), so the two receivers share one time axis.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import signal

CLIP_FRACTION = 0.98  # KTD7: |I| or |Q| at or above 98% of full scale counts as clipped


def block_stats(iq: np.ndarray, full_scale: int, clip_fraction: float = CLIP_FRACTION):
    """Peak (dBFS), mean power (dBFS) and number of clipped samples of an (n, 2) int16 block.

    Peak is the largest |I| or |Q| relative to full scale. Power is the mean of
    I² + Q² relative to full scale squared.
    """
    if len(iq) == 0:
        return -math.inf, -math.inf, 0
    hi = int(iq.max())
    lo = int(iq.min())
    peak = max(hi, -lo)
    thr = clip_fraction * full_scale
    clipped = 0
    if peak >= thr:  # rare: only then count the clipped samples
        clipped = int(np.count_nonzero(((iq >= thr) | (iq <= -thr)).any(axis=1)))
    f = iq.astype(np.float32)
    power = float(np.einsum("ij,ij->", f, f)) / len(iq)
    peak_db = 20 * math.log10(peak / full_scale) if peak > 0 else -math.inf
    pwr_db = 10 * math.log10(power / full_scale**2) if power > 0 else -math.inf
    return peak_db, pwr_db, clipped


class IntervalTracker:
    """Turns per-block flags into intervals with hysteresis.

    An interval opens at the start of the first flagged block and closes once
    ``hold`` samples of unflagged blocks have followed the last flagged one.
    Two bursts closer than ``hold`` therefore form one interval.
    """

    def __init__(self, hold: int):
        self.hold = hold
        self.start: int | None = None
        self.last_end: int | None = None

    @property
    def is_open(self) -> bool:
        return self.start is not None

    def update(self, start: int, end: int, flagged: bool) -> tuple[int, int] | None:
        if flagged:
            if self.start is None:
                self.start = start
            self.last_end = end
            return None
        if self.start is not None and end - self.last_end >= self.hold:
            return self.flush()
        return None

    def flush(self) -> tuple[int, int] | None:
        if self.start is None:
            return None
        interval = (self.start, self.last_end)
        self.start = self.last_end = None
        return interval


def design_lowpass(fs: float, factor: int, passband_hz: float, stop_db: float = 80.0) -> np.ndarray:
    """Kaiser lowpass for decimation by ``factor``: flat to ``passband_hz``, alias-free there.

    The stopband starts at ``fs/factor - passband_hz``, the first frequency that
    would alias into the passband. The length is rounded up to a multiple of
    ``factor`` for the polyphase form.
    """
    fs_out = fs / factor
    stop_hz = fs_out - passband_hz
    if stop_hz <= passband_hz:
        raise ValueError("passband too wide for the output rate")
    width = (stop_hz - passband_hz) / (fs / 2)
    numtaps, beta = signal.kaiserord(stop_db, width)
    numtaps = int(math.ceil(numtaps / factor) * factor)
    cutoff = (passband_hz + stop_hz) / 2
    return signal.firwin(numtaps, cutoff, window=("kaiser", beta), fs=fs).astype(np.float32)


class Decimator:
    """Digital down-conversion and polyphase FIR decimation with state across blocks.

    The slice centred ``shift_hz`` above the tuner centre is moved to 0 Hz and
    decimated by ``factor``. Output sample k of a segment corresponds to the
    wide counter ``(g0 + k) * factor``, where ``g0 = ceil(c0 / factor)`` and
    ``c0`` is the counter at which the segment started (``reset``). The filter is
    causal: its delay is ``(len(taps) - 1) / 2`` wide samples, and the first
    ``len(taps) // factor`` outputs of a segment contain the start-up transient.
    The NCO phase is computed from the absolute counter, so it is the same on
    both receivers and continuous across blocks.
    """

    def __init__(self, fs: float, factor: int, shift_hz: int, taps: np.ndarray, full_scale: int):
        if int(fs) != fs or len(taps) % factor:
            raise ValueError("integer sample rate and taps multiple of factor required")
        self.fs = int(fs)
        self.factor = factor
        self.shift_hz = int(shift_hz)
        self.taps = taps
        self.q = len(taps) // factor
        self._hr = taps[::-1].astype(np.complex64).reshape(self.q, factor)
        self.scale = np.float32(1.0 / full_scale)
        self._buf = np.zeros(0, np.complex64)
        self._next = None  # counter of the next input sample expected

    @property
    def delay_samples(self) -> float:
        return (len(self.taps) - 1) / 2

    @property
    def transient_outputs(self) -> int:
        return self.q

    def reset(self, counter: int) -> int:
        """Start a segment at ``counter``; return g0, the narrow index of its first output."""
        g0 = -(-counter // self.factor)
        lead = self.q * self.factor - 1 - (g0 * self.factor - counter)
        self._buf = np.zeros(lead, np.complex64)
        self._next = counter
        return g0

    def process(self, iq: np.ndarray, counter: int) -> np.ndarray:
        """Feed an (n, 2) int16 block starting at ``counter``; return the new narrow outputs."""
        if counter != self._next:
            raise ValueError(f"discontinuous input: expected {self._next}, got {counter}")
        n = len(iq)
        self._next = counter + n
        x = (iq[:, 0].astype(np.float32) + 1j * iq[:, 1].astype(np.float32)) * self.scale
        if self.shift_hz:
            base = (self.shift_hz * counter) % self.fs
            ph = (base + self.shift_hz * np.arange(n, dtype=np.float64)) * (-2 * np.pi / self.fs)
            x = x * np.exp(1j * ph).astype(np.complex64)
        buf = np.concatenate((self._buf, x.astype(np.complex64)))
        qd = self.q * self.factor
        p0 = qd - 1
        if len(buf) <= p0:
            self._buf = buf
            return np.zeros(0, np.complex64)
        k = (len(buf) - 1 - p0) // self.factor + 1
        rows = buf[: (self.q + k - 1) * self.factor].reshape(self.q + k - 1, self.factor)
        y = np.zeros(k, np.complex64)
        for j in range(self.q):
            y += rows[j : j + k] @ self._hr[j]
        self._buf = buf[k * self.factor :]
        return y
