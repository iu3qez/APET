"""``reapet record`` end to end with the simulated device (F1)."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sigmf import sigmffile

from reapet.cli import main


def _session(out: Path) -> Path:
    (path,) = out.iterdir()
    return path


def _record(tmp_path, *extra):
    return main(
        [
            "record",
            "--fake",
            "--no-sntp",
            "--out",
            str(tmp_path / "s"),
            "--antenna-a",
            "loop",
            "--antenna-b",
            "dipole",
            "--locator",
            "JN65ag",
            *extra,
        ]
    )


def test_record_30_s_produces_valid_session(tmp_path, capsys):
    assert _record(tmp_path, "--duration", "30") == 0
    out = capsys.readouterr().out
    assert "CLOSED (stop)" in out and "sat 0" in out
    path = _session(tmp_path / "s")
    for name in ("rx-A", "rx-B"):
        f = sigmffile.fromfile(str(path / name))
        f.validate()
        assert abs(f.sample_count / 62_500 - 30) < 1.5
        g = f.get_global_field
        assert g("reapet:locator") == "JN65ag"
        assert g("reapet:band")["band"] == "20m"
        assert g("reapet:gain")["margin_met"]
        assert len(g("reapet:readback")) == 2
        assert g("reapet:saturation_detection")["device_overload"]["available"]
        assert g("reapet:clock_start")["state"] == "unknown"
    sigmffile.fromfile(str(path / "session.sigmf-collection")).verify_stream_hashes()


def test_record_with_wide_band(tmp_path):
    assert _record(tmp_path, "--duration", "2", "--store-wide") == 0
    path = _session(tmp_path / "s")
    wide = sigmffile.fromfile(str(path / "rx-A-wide"))
    narrow = sigmffile.fromfile(str(path / "rx-A"))
    assert wide.get_global_field("core:datatype") == "ci16_le"
    assert abs(wide.sample_count / 32 - narrow.sample_count) < 64


def test_record_refuses_unsuitable_device(tmp_path, capsys):
    scen = tmp_path / "one.json"
    scen.write_text(json.dumps({"receivers": 1}))
    assert _record(tmp_path, "--fake-scenario", str(scen)) == 2
    assert "two receivers" in capsys.readouterr().out
    assert not (tmp_path / "s").exists()


def test_record_refuses_tuners_that_read_back_differently(tmp_path, capsys):
    scen = tmp_path / "diff.json"
    scen.write_text(json.dumps({"readback_offset_b": {"if_gr_db": 2}}))
    assert _record(tmp_path, "--fake-scenario", str(scen), "--duration", "1") == 3
    assert "tuners differ" in capsys.readouterr().out
    assert not (tmp_path / "s").exists()


def test_ctrl_c_produces_closed_valid_session(tmp_path):
    out = tmp_path / "s"
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "reapet.cli",
            "record",
            "--fake",
            "--no-sntp",
            "--out",
            str(out),
            "--antenna-a",
            "a",
            "--antenna-b",
            "b",
            "--locator",
            "",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    deadline = time.monotonic() + 30
    for line in proc.stdout:
        if line.startswith("Recording to"):
            break
        assert time.monotonic() < deadline
    time.sleep(2)
    proc.send_signal(signal.SIGINT)
    rest = proc.communicate(timeout=30)[0]
    assert proc.returncode == 0, rest
    path = _session(out)
    meta = json.loads((path / "rx-A.sigmf-meta").read_text())
    assert meta["global"]["reapet:close"]["reason"] == "stop"
    assert meta["global"]["reapet:missing"] == ["locator"]
    sigmffile.fromfile(str(path / "rx-B")).validate()
