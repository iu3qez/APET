import json

from sigmf import sigmffile

from reapet.fake_device import FakeScenario
from reapet.session import BLOCK_DTYPE, read_blocks, recover


def _meta(path, name):
    return json.loads((path / f"{name}.sigmf-meta").read_text())


def _open_sigmf(path, name):
    f = sigmffile.fromfile(str(path / name))
    f.validate()
    return f


def test_closed_session_reads_back_with_sigmf(harness):
    h = harness()
    h.run_seconds(1.0)
    h.rec.close("stop")
    a, b = _open_sigmf(h.session.path, "rx-A"), _open_sigmf(h.session.path, "rx-B")
    assert a.sample_count == b.sample_count > 0
    assert a.get_captures() == b.get_captures()
    coll = sigmffile.fromfile(str(h.session.path / "session.sigmf-collection"))
    coll.verify_stream_hashes()
    assert coll.get_stream_names() == ["rx-A", "rx-B"]
    assert a.get_global_field("antenna:model") == "loop"
    assert b.get_global_field("antenna:model") == "dipole"
    assert a.get_global_field("reapet:close")["reason"] == "stop"


def test_annotations_sorted_with_reapet_keys(harness):
    h = harness(FakeScenario(clipping=((0, 0.2, 0.1), (0, 1.6, 0.1)), overload=((0, 0.5, 0.2),)))
    h.run_seconds(3.0)
    h.rec.close("stop")
    anns = _meta(h.session.path, "rx-A")["annotations"]
    starts = [a["core:sample_start"] for a in anns]
    assert starts == sorted(starts)
    assert {a["core:label"] for a in anns} >= {"saturation", "overload", "session_end"}
    assert all(any(k.startswith("reapet:") for k in a) for a in anns)


def test_truncated_data_valid_after_recover(harness):
    h = harness()
    h.run_seconds(1.0)
    h.rec._flush_stage()
    h.session.sync()
    path = h.session.path
    # simulate a crash: files stay as they are, A ends mid-sample, journal ends mid-line
    with open(path / "rx-A.sigmf-data", "ab") as f:
        f.write(b"\x01\x02\x03")
    with open(path / "journal.jsonl", "a") as f:
        f.write('{"type": "interval_open", "chan')
    with open(path / "blocks.bin", "ab") as f:
        f.write(b"\x00" * 5)
    recover(path)
    a, b = _open_sigmf(path, "rx-A"), _open_sigmf(path, "rx-B")
    assert a.sample_count == b.sample_count > 0
    labels = [x["core:label"] for x in a.get_annotations()]
    assert labels[-1] == "session_end"
    assert a.get_global_field("reapet:close")["reason"] == "abnormal_close"
    assert (path / "blocks.bin").stat().st_size % BLOCK_DTYPE.itemsize == 0


def test_gap_opens_same_segment_on_both(harness):
    h = harness(FakeScenario(counter_gaps=((1, 0.3, 5000),)))
    h.run_seconds(1.0)
    h.rec.close("stop")
    ma, mb = _meta(h.session.path, "rx-A"), _meta(h.session.path, "rx-B")
    assert len(ma["captures"]) == 2
    assert ma["captures"] == mb["captures"]
    gaps = [a for a in ma["annotations"] if a["core:label"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["reapet:missing_channels"] == ["B"]
    assert gaps[0]["reapet:counter_end"] - gaps[0]["reapet:counter_start"] == 5000


def test_missing_locator_is_missing_not_empty(harness):
    h = harness()
    h.run_seconds(0.2)
    h.rec.close("stop")
    g = _meta(h.session.path, "rx-A")["global"]
    assert g["reapet:locator"] is None
    assert "locator" in g["reapet:missing"]
    assert "core:geolocation" not in g


def test_block_table_has_one_row_per_block(harness):
    h = harness()
    h.run_seconds(0.5)
    h.rec.close("stop")
    rows = read_blocks(h.session.path)
    assert set(rows["channel"]) == {0, 1}
    assert (rows["n"] == 2048).all()
    a = rows[rows["channel"] == 0]
    assert (a["counter"][1:] - a["counter"][:-1] == 2048).all()
