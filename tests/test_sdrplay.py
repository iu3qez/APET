"""Binding details that can be checked without the library."""

import ctypes

from reapet import sdrplay


def test_device_struct_layout():
    # char[64], uchar, enum, enum, uchar, double, HANDLE (spec 2.1.4), natural alignment
    assert sdrplay.DeviceT.hwVer.offset == 64
    assert sdrplay.DeviceT.tuner.offset == 68
    assert sdrplay.DeviceT.valid.offset == 76
    assert sdrplay.DeviceT.rspDuoSampleFreq.offset == 80
    assert sdrplay.DeviceT.dev.offset == 88
    assert ctypes.sizeof(sdrplay.DeviceT) == 88 + ctypes.sizeof(ctypes.c_void_p)


def test_stream_params_layout():
    assert sdrplay.StreamCbParamsT.numSamples.offset == 16
    assert ctypes.sizeof(sdrplay.StreamCbParamsT) == 20


def test_unwrap_handles_32_bit_wrap():
    u = sdrplay._Unwrapper()
    n = 1000
    start = (1 << 32) - 2500
    counters = [u.push((start + k * n) & 0xFFFFFFFF, n)[0] for k in range(5)]
    assert counters == [start + k * n for k in range(5)]


def test_unwrap_learns_counter_step():
    u = sdrplay._Unwrapper()
    out = [u.push(k * 3 * 1000, 1000)[0] for k in range(4)]
    assert u.step == 3
    assert out[1:] == [1000, 2000, 3000]


def test_unwrap_flags_backward_jump_as_reset():
    u = sdrplay._Unwrapper()
    u.push(50_000, 1000)
    u.push(51_000, 1000)
    _, reset = u.push(10, 1000)
    assert reset


def test_gain_ladder_runs_from_high_to_low_gain():
    steps = sdrplay.gain_ladder(sdrplay.LNA_GR_50OHM)
    totals = [s.total_gr_db for s in steps]
    assert totals == sorted(totals)
    assert totals[0] == 20 and totals[-1] == 61 + 59
    assert all(20 <= s.if_gr_db <= 59 for s in steps)
    assert all(b > a for a, b in zip(totals, totals[1:], strict=False))
