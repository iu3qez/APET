import numpy as np
import pytest

from reapet.dsp import Decimator, IntervalTracker, block_stats, design_lowpass

FS = 2_000_000
D = 32
SHIFT = 200_000
FS_OUT = FS / D


def _tone(f_hz, n, start=0, amp=8000.0):
    k = start + np.arange(n)
    x = amp * np.exp(2j * np.pi * f_hz * k / FS)
    return np.stack([np.round(x.real), np.round(x.imag)], axis=1).astype(np.int16)


def _decimator(taps=None):
    taps = design_lowpass(FS, D, 25_000) if taps is None else taps
    return Decimator(FS, D, SHIFT, taps, 32767)


def _peak_freq(y):
    spec = np.abs(np.fft.fft(y * np.hanning(len(y))))
    f = np.fft.fftfreq(len(y), 1 / FS_OUT)
    return f[np.argmax(spec)]


def test_tone_lands_at_expected_frequency():
    dec = _decimator()
    dec.reset(0)
    y = dec.process(_tone(SHIFT + 1_500, 1 << 18), 0)[dec.transient_outputs :]
    assert abs(_peak_freq(y) - 1_500) < FS_OUT / len(y) * 2
    assert np.abs(y).max() == pytest.approx(8000 / 32767, rel=0.01)


def test_out_of_slice_tone_attenuated_as_specified():
    dec = _decimator()
    dec.reset(0)
    inside = dec.process(_tone(SHIFT + 5_000, 1 << 17), 0)[dec.transient_outputs :]
    dec.reset(0)
    # 45 kHz from the slice centre would alias to -17.5 kHz without the filter
    outside = dec.process(_tone(SHIFT + 45_000, 1 << 17), 0)[dec.transient_outputs :]
    ratio_db = 20 * np.log10(np.abs(outside).max() / np.abs(inside).max())
    assert ratio_db < -78


def test_block_by_block_equals_one_shot():
    x = (np.random.default_rng(3).normal(0, 3000, (40_000, 2))).astype(np.int16)
    one = _decimator()
    one.reset(17)
    y_one = one.process(x, 17)
    blk = _decimator()
    blk.reset(17)
    pieces, c = [], 17
    for size in (1, 31, 500, 4096, 13, 2048, 33_360):
        pieces.append(blk.process(x[c - 17 : c - 17 + size], c))
        c += size
    y_blk = np.concatenate(pieces)
    assert len(y_blk) == len(y_one)
    np.testing.assert_allclose(y_blk, y_one, rtol=1e-4, atol=1e-6)


def test_output_grid_follows_counter():
    dec = _decimator()
    g0 = dec.reset(100)
    assert g0 == 4  # ceil(100 / 32)
    y = dec.process(np.zeros((3200, 2), np.int16), 100)
    # outputs at counters 128, 160, ..., 3296: (3296 - 128) / 32 + 1
    assert len(y) == 100


def test_discontinuous_input_rejected():
    dec = _decimator()
    dec.reset(0)
    dec.process(np.zeros((64, 2), np.int16), 0)
    with pytest.raises(ValueError):
        dec.process(np.zeros((64, 2), np.int16), 65)


def test_block_stats():
    iq = np.array([[32767, 0], [0, -32700], [100, 100]], np.int16)
    peak, power, clipped = block_stats(iq, 32767)
    assert peak == pytest.approx(0.0)
    assert clipped == 2
    assert power < 0


def test_bursts_closer_than_hold_merge():
    t = IntervalTracker(hold=100)
    assert t.update(0, 10, True) is None
    assert t.update(10, 60, False) is None
    assert t.update(60, 70, True) is None
    assert t.update(70, 200, False) == (0, 70)


def test_bursts_farther_than_hold_split():
    t = IntervalTracker(hold=100)
    t.update(0, 10, True)
    assert t.update(10, 120, False) == (0, 10)
    t.update(120, 130, True)
    assert t.flush() == (120, 130)
