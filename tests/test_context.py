import struct

import pytest

from reapet.context import (
    NTP_EPOCH_OFFSET,
    ask_context,
    clock_check,
    locator_center,
    normalize_locator,
    sntp_query,
)


def _answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def test_empty_locator_is_missing_without_geolocation():  # AE2
    ctx = ask_context(input_fn=_answers("loop", "dipole", ""), print_fn=lambda s: None)
    assert ctx["locator"] is None
    assert ctx["geolocation"] is None
    assert ctx["missing"] == ["locator"]
    assert ctx["antennas"] == {"A": "loop", "B": "dipole"}


def test_invalid_locator_is_asked_again_then_missing():
    said = []
    ctx = ask_context(input_fn=_answers("loop", "dipole", "JN6", ""), print_fn=said.append)
    assert any("JN6" in s for s in said)
    assert ctx["locator"] is None and "locator" in ctx["missing"]


def test_invalid_locator_then_valid():
    ctx = ask_context(input_fn=_answers("", "dipole", "JN6", "jn65AG"), print_fn=lambda s: None)
    assert ctx["locator"] == "JN65ag"
    assert ctx["missing"] == ["antenna_a"]


def test_given_answers_are_not_asked():
    def no_input(prompt):
        raise AssertionError("asked")

    ctx = ask_context(input_fn=no_input, given={"antenna_a": "a", "antenna_b": "b", "locator": ""})
    assert ctx["missing"] == ["locator"]


@pytest.mark.parametrize(
    "loc, lat, lon, tol_lat, tol_lon",
    [("JN65", 45.5, 13.0, 0.5, 1.0), ("JN65ag", 45.270833, 12.041667, 1.25 / 60, 2.5 / 60)],
)
def test_square_centres(loc, lat, lon, tol_lat, tol_lon):
    c_lat, c_lon, h, w = locator_center(loc)
    assert c_lat == pytest.approx(lat, abs=1e-6)
    assert c_lon == pytest.approx(lon, abs=1e-6)
    assert (h, w) == pytest.approx((tol_lat, tol_lon))


def test_normalize_locator():
    assert normalize_locator("jn65ag") == "JN65ag"
    assert normalize_locator("JN6") is None
    assert normalize_locator("ZZ00") is None


def _ntp(ns):
    s = ns // 1_000_000_000 + NTP_EPOCH_OFFSET
    frac = ((ns % 1_000_000_000) << 32) // 1_000_000_000
    return struct.pack("!II", s, frac)


def test_sntp_offset_rtt_and_server():
    t1 = 1_800_000_000_000_000_000
    t4 = t1 + 40_000_000  # 40 ms round trip, server answers instantly
    t2 = t3 = t1 + 20_000_000 + 350_000_000  # server clock 350 ms ahead

    def transport(server, packet, timeout):
        reply = bytes([0x24, 2]) + bytes(30) + _ntp(t2) + _ntp(t3)
        return reply, t1, t4

    r = sntp_query("ntp.example", transport=transport)
    assert r["offset_s"] == pytest.approx(0.35, abs=1e-6)
    assert r["rtt_s"] == pytest.approx(0.04, abs=1e-6)
    assert r["server"] == "ntp.example"
    rec = clock_check(servers=("ntp.example",), transport=transport, os_status=lambda: None)
    assert rec["state"] == "not_synchronised"
    assert rec["sntp"]["offset_s"] == pytest.approx(0.35, abs=1e-6)


def test_without_network_clock_is_unknown():  # AE4
    def offline(server, packet, timeout):
        raise OSError("Network is unreachable")

    rec = clock_check(transport=offline, os_status=lambda: None)
    assert rec["state"] == "unknown"
    assert "offset_s" not in rec
    assert len(rec["sntp_errors"]) == 3
