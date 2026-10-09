import errno
import json

import numpy as np

from reapet.acquisition import BlockQueue
from reapet.fake_device import FakeScenario, Tone

from .conftest import FACTOR, FS, read_cf32


def _meta(path, name):
    return json.loads((path / f"{name}.sigmf-meta").read_text())


def _labels(path, name, label):
    return [a for a in _meta(path, name)["annotations"] if a["core:label"] == label]


def test_clipping_on_a_gives_saturation_on_a_only(harness):  # AE1
    h = harness(FakeScenario(clipping=((0, 1.0, 40.0),)))
    assert h.run_seconds(43.0)
    h.rec.close("stop")
    sat_a = _labels(h.session.path, "rx-A", "saturation")
    assert len(sat_a) == 1
    secs = sat_a[0]["core:sample_count"] / (FS / FACTOR)
    assert abs(secs - 40.0) < 0.01
    assert _labels(h.session.path, "rx-B", "saturation") == []
    assert _meta(h.session.path, "rx-A")["global"]["reapet:close"]["reason"] == "stop"


def test_overload_event_on_b_has_start_and_end(harness):
    h = harness(FakeScenario(overload=((1, 0.5, 0.5),)))
    h.run_seconds(1.5)
    h.rec.close("stop")
    ovl = _labels(h.session.path, "rx-B", "overload")
    assert len(ovl) == 1
    assert ovl[0]["reapet:source"] == "device"
    assert abs(ovl[0]["core:sample_count"] / (FS / FACTOR) - 0.5) < 0.01
    assert _labels(h.session.path, "rx-A", "overload") == []


def test_counter_gap_on_b_only(harness):
    h = harness(FakeScenario(counter_gaps=((1, 0.4, 3000),)))
    h.run_seconds(1.0)
    h.rec.close("stop")
    path = h.session.path
    a, b = read_cf32(path / "rx-A.sigmf-data"), read_cf32(path / "rx-B.sigmf-data")
    assert len(a) == len(b)
    ca, cb = _meta(path, "rx-A")["captures"], _meta(path, "rx-B")["captures"]
    assert ca == cb and len(ca) == 2
    assert ca[1]["reapet:counter"] - ca[0]["reapet:counter"] > 0


def test_samples_stay_aligned_across_a_gap(harness):
    # one common tone: after the gap both narrow streams must still be identical in phase
    sc = FakeScenario(
        tones=(Tone(200_000 + 2_000, -20.0),), noise_dbfs=-90, counter_gaps=((0, 0.3, 4321),)
    )
    h = harness(sc)
    h.run_seconds(1.0)
    h.rec.close("stop")
    path = h.session.path
    a, b = read_cf32(path / "rx-A.sigmf-data"), read_cf32(path / "rx-B.sigmf-data")
    seg2 = _meta(path, "rx-A")["captures"][1]["core:sample_start"]
    tail = slice(seg2 + 200, None)  # past the filter transient
    np.testing.assert_allclose(a[tail], b[tail], atol=1e-3)


def test_swapped_arrival_order_still_pairs(harness):
    h = harness(FakeScenario(swap_order=True, tones=(Tone(202_000, -20.0),), noise_dbfs=-90))
    h.run_seconds(0.5)
    h.rec.close("stop")
    path = h.session.path
    a, b = read_cf32(path / "rx-A.sigmf-data"), read_cf32(path / "rx-B.sigmf-data")
    assert len(a) == len(b) > 0
    assert len(_meta(path, "rx-A")["captures"]) == 1
    np.testing.assert_allclose(a[200:], b[200:], atol=1e-3)


def test_link_drop_closes_session_with_interruption(harness):  # AE3
    h = harness(FakeScenario(stop_at_s=1.0))
    assert not h.run_seconds(5.0)
    h.idle(5.0)
    assert h.rec.closed
    close = _meta(h.session.path, "rx-A")["global"]["reapet:close"]
    assert close["reason"] == "disconnection"
    assert close["counter_end"] == int(1.0 * FS / 2048 + 1) * 2048
    end = _labels(h.session.path, "rx-A", "session_end")
    assert end[0]["reapet:reason"] == "disconnection"


def test_device_removed_event_closes_session(harness):
    h = harness(FakeScenario(removed_at_s=0.5))
    h.run_seconds(2.0)
    assert h.rec.closed
    assert _meta(h.session.path, "rx-A")["global"]["reapet:close"]["reason"] == "disconnection"


def test_full_queue_drops_block_as_gap_without_blocking():
    q = BlockQueue(4096)
    i = np.zeros(2048, np.int16)
    q.push_block(0, 0, i, i, 0)
    q.push_block(0, 2048, i, i, 0)
    q.push_block(0, 4096, i, i, 0)  # no room: dropped, not blocked
    assert q.dropped_blocks == [1, 0]
    assert q.was_dropped(0, 4096, 6144)


def test_slow_writer_gap_declared_as_queue_full(harness):
    h = harness()
    small = BlockQueue(2048 * 3)
    h.rec.q = small
    h.q = small
    h.dev.produce(small, 4)  # 8 blocks offered, ring holds 3 per receiver
    h.drain()
    h.run_seconds(0.1)
    h.rec.close("stop")
    gaps = _labels(h.session.path, "rx-A", "gap")
    assert gaps and gaps[0]["reapet:reason"] == "queue_full"


def test_disk_margin_closes_session(harness):
    h = harness()
    h.run_seconds(0.5)
    h.disk_free = 1000
    h.run_seconds(1.0)
    assert h.rec.closed
    close = _meta(h.session.path, "rx-A")["global"]["reapet:close"]
    assert close["reason"] == "disk_limit"


def test_disk_full_error_closes_session_without_recover(harness):
    h = harness()
    h.run_seconds(0.5)
    real_write = h.session.write

    def full(stream, samples):
        raise OSError(errno.ENOSPC, "No space left on device")

    h.session.write = full
    h.run_seconds(0.5)
    assert h.rec.closed
    h.session.write = real_write
    meta = _meta(h.session.path, "rx-A")
    assert meta["global"]["reapet:close"]["reason"] == "disk_full"
    assert meta["global"]["reapet:state"] == "closed"


def test_close_before_any_pairing_is_still_valid(harness):
    h = harness(FakeScenario(clipping=((0, 0.0, 1.0),)))
    i, q = h.dev.make_block(0)[1:]
    h.q.push_block(0, 0, i, q, 0)  # only receiver A ever delivers
    h.drain()
    h.idle(5.0)
    meta = _meta(h.session.path, "rx-A")
    assert meta["global"]["reapet:close"]["reason"] == "disconnection"
    assert meta["captures"] == []
    assert [a["core:label"] for a in meta["annotations"]] == ["saturation", "session_end"]
