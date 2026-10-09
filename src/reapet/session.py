"""Session storage: a SigMF Collection with one recording per antenna (KTD2, KTD9).

While recording, samples are appended to the ``.sigmf-data`` files and every
event goes to an append-only journal (``journal.jsonl``). The SigMF metadata is
always built from the journal plus the data files, at close or by ``recover``,
so a crash loses at most the unsynced tail.

Positions in the journal are wide-band counter values. They are mapped to the
sample index of each recording when the metadata is built.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sigmf

from . import __version__

JOURNAL = "journal.jsonl"
BLOCKS = "blocks.bin"
COLLECTION = "session"

# One row per received block and receiver (KTD4).
BLOCK_DTYPE = np.dtype(
    [
        ("channel", "u1"),
        ("flags", "u1"),
        ("n", "<u4"),
        ("counter", "<i8"),
        ("t_ns", "<i8"),
        ("peak_dbfs", "<f4"),
        ("power_dbfs", "<f4"),
        ("clipped", "<u4"),
    ]
)

DTYPE_SIZES = {"cf32_le": 8, "ci16_le": 4}

EXTENSIONS = [
    {"name": "antenna", "version": "1.0.0", "optional": True},
    {"name": "reapet", "version": "0.1.0", "optional": True},
]


@dataclass(frozen=True)
class StreamSpec:
    """One recording of the collection."""

    name: str  # file stem, e.g. "rx-A"
    channel: str  # "A" or "B"
    kind: str  # "narrow" or "wide"
    datatype: str
    sample_rate: float
    center_hz: float  # RF frequency at 0 Hz of the recording

    @property
    def sample_size(self) -> int:
        return DTYPE_SIZES[self.datatype]

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def iso_utc(t_ns: int) -> str:
    t = dt.datetime.fromtimestamp(t_ns // 1_000_000_000, tz=dt.UTC)
    frac = t_ns % 1_000_000_000
    return t.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac:09d}Z"


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Session:
    """An open session being written."""

    def __init__(self, path: Path, header: dict, streams: list[StreamSpec]):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=False)
        self.streams = {s.name: s for s in streams}
        self._data = {s.name: open(self.path / f"{s.name}.sigmf-data", "wb") for s in streams}
        self._journal = open(self.path / JOURNAL, "a", encoding="utf-8")
        self._blocks = open(self.path / BLOCKS, "wb")
        self.closed = False
        self._lock = threading.Lock()
        self.journal(
            {
                "type": "open",
                "reapet_version": __version__,
                "streams": [s.as_dict() for s in streams],
                **header,
            }
        )
        self.sync()
        build_metadata(self.path)  # provisional metadata (KTD9)

    def journal(self, record: dict) -> None:
        """Append one record. Called by the writer and by the clock monitor thread."""
        with self._lock:
            if self._journal.closed:
                return
            self._journal.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._journal.flush()

    def write(self, stream: str, samples: np.ndarray) -> None:
        self._data[stream].write(samples.tobytes())

    def add_blocks(self, rows: np.ndarray) -> None:
        self._blocks.write(rows.astype(BLOCK_DTYPE, copy=False).tobytes())

    def sync(self) -> None:
        for f in (*self._data.values(), self._journal, self._blocks):
            f.flush()
            os.fsync(f.fileno())

    def close(self, reason: str, counter_end: int | None, t_ns: int, detail: dict | None = None):
        """Write the close record and the final metadata. Safe to call once."""
        if self.closed:
            return
        self.closed = True
        errors = []
        for f in (*self._data.values(), self._blocks):
            try:
                f.flush()
                os.fsync(f.fileno())
            except OSError as e:  # disk full: the data written so far stays valid
                errors.append(str(e))
            finally:
                with contextlib.suppress(OSError):
                    f.close()
        record = {
            "type": "close",
            "reason": reason,
            "counter_end": counter_end,
            "t_ns": t_ns,
            **(detail or {}),
        }
        if errors:
            record["flush_errors"] = errors
        self.journal(record)
        with self._lock:
            os.fsync(self._journal.fileno())
            self._journal.close()
        return build_metadata(self.path)


# --- metadata --------------------------------------------------------------------


def read_journal(path: Path) -> list[dict]:
    records = []
    with open(Path(path) / JOURNAL, encoding="utf-8") as f:
        for line in f:
            if not line.endswith("\n"):
                break  # torn last line after a crash
            records.append(json.loads(line))
    return records


def _sha512(path: Path, size: int) -> str:
    h = hashlib.sha512()
    with open(path, "rb") as f:
        remaining = size
        while remaining > 0:
            chunk = f.read(min(remaining, 1 << 22))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


class _Timeline:
    """Maps wide counter values to sample indices of a recording, through the segments."""

    def __init__(self, segments: list[dict], factor: int, kind: str, n_samples: int):
        self.segments = segments
        self.factor = factor
        self.kind = kind
        self.n = n_samples

    def _start(self, seg: dict) -> int:
        return seg["wide_index"] if self.kind == "wide" else seg["narrow_index"]

    def index(self, counter: int) -> int:
        segs = self.segments
        if not segs:  # closed before the two receivers were ever paired
            return 0
        k = 0
        for j, seg in enumerate(segs):
            if seg["counter"] <= counter:
                k = j
        seg = segs[k]
        if counter < seg["counter"]:
            return self._start(seg)
        if self.kind == "wide":
            idx = seg["wide_index"] + (counter - seg["counter"])
        else:
            idx = seg["narrow_index"] + (counter // self.factor - seg["g0"])
        upper = self._start(segs[k + 1]) if k + 1 < len(segs) else self.n
        return max(self._start(seg), min(idx, upper))

    def end_counter(self) -> int | None:
        if not self.segments:
            return None
        seg = self.segments[-1]
        if self.kind == "wide":
            return seg["counter"] + (self.n - seg["wide_index"])
        return (seg["g0"] + self.n - seg["narrow_index"]) * self.factor


def _context_globals(header: dict) -> dict:
    ctx = header.get("context", {})
    out = {f"reapet:{k}": v for k, v in ctx.items()}
    out["reapet:version"] = header.get("reapet_version")
    out["reapet:decimation"] = header.get("decimation")
    out["reapet:block_table"] = {"file": BLOCKS, "dtype": BLOCK_DTYPE.descr}
    return out


def build_metadata(path: Path) -> dict:
    """Build every ``.sigmf-meta`` and the ``.sigmf-collection`` from the journal."""
    path = Path(path)
    records = read_journal(path)
    header = records[0]
    if header.get("type") != "open":
        raise ValueError("journal does not start with an open record")
    streams = [StreamSpec(**s) for s in header["streams"]]
    factor = header["decimation"]["factor"]
    segments = [r for r in records if r["type"] == "segment"]
    gaps = [r for r in records if r["type"] == "gap"]
    closes = [r for r in records if r["type"] == "close"]
    clock = [r for r in records if r["type"] == "clock"]
    opened = {}
    intervals = []
    for r in records:
        key = (r.get("channel"), r.get("kind"), r.get("counter_start"))
        if r["type"] == "interval_open":
            opened[key] = r
        elif r["type"] == "interval":
            opened.pop(key, None)
            intervals.append(r)
    close = closes[-1] if closes else None
    ctx = header.get("context", {})
    antennas = ctx.get("antennas", {})
    meta_paths = {}

    for spec in streams:
        data_path = path / f"{spec.name}.sigmf-data"
        size = data_path.stat().st_size if data_path.exists() else 0
        n = size // spec.sample_size
        timeline = _Timeline(segments, factor, spec.kind, n)

        captures = []
        for seg in segments:
            start = timeline._start(seg)
            if captures and start >= n:
                continue
            capture = {
                "core:sample_start": start,
                "core:global_index": seg["counter"] if spec.kind == "wide" else seg["g0"],
                "core:frequency": spec.center_hz,
                "core:datetime": iso_utc(seg["t_ns"]),
                "reapet:counter": seg["counter"],
            }
            if captures and captures[-1]["core:sample_start"] == start:
                captures[-1] = capture  # an empty segment is superseded by the next one
            else:
                captures.append(capture)

        annotations = []
        for r in intervals + [
            dict(o, counter_end=timeline.end_counter(), closed_by="session_end")
            for o in opened.values()
        ]:
            if r["channel"] != spec.channel or r.get("counter_end") is None:
                continue
            a = timeline.index(r["counter_start"])
            b = timeline.index(r["counter_end"])
            ann = {
                "core:sample_start": a,
                "core:sample_count": max(b - a, 1),
                "core:label": r["kind"],
                "reapet:source": "iq" if r["kind"] == "saturation" else "device",
                "reapet:counter_start": r["counter_start"],
                "reapet:counter_end": r["counter_end"],
            }
            if "closed_by" in r:
                ann["reapet:closed_by"] = r["closed_by"]
            annotations.append(ann)
        for g in gaps:
            annotations.append(
                {
                    "core:sample_start": timeline.index(g["counter_end"]),
                    "core:label": "gap",
                    "core:comment": f"{g['counter_end'] - g['counter_start']} wide samples missing "
                    f"on {', '.join(g['channels'])} ({g['reason']}); dropped on both",
                    "reapet:counter_start": g["counter_start"],
                    "reapet:counter_end": g["counter_end"],
                    "reapet:missing_channels": g["channels"],
                    "reapet:reason": g["reason"],
                }
            )
        if close is not None:
            annotations.append(
                {
                    "core:sample_start": max(n - 1, 0),
                    "core:sample_count": 1 if n else 0,
                    "core:label": "session_end",
                    "core:comment": close["reason"],
                    "reapet:reason": close["reason"],
                    "reapet:counter_end": close.get("counter_end"),
                }
            )
        annotations.sort(key=lambda x: x["core:sample_start"])

        glob = {
            "core:datatype": spec.datatype,
            "core:sample_rate": spec.sample_rate,
            "core:version": sigmf.__specification__,
            "core:num_channels": 1,
            "core:recorder": f"reAPET {header.get('reapet_version')}",
            "core:hw": ctx.get("device", {}).get("name", "unknown"),
            "core:collection": COLLECTION,
            "core:extensions": EXTENSIONS,
            "core:description": f"reAPET session, receiver {spec.channel}, {spec.kind} band",
            "core:sha512": _sha512(data_path, size) if size else hashlib.sha512().hexdigest(),
            "reapet:channel": spec.channel,
            "reapet:kind": spec.kind,
            "reapet:state": "closed" if close else "recording",
            "reapet:close": close,
            "reapet:clock_checks": clock,
            **_context_globals(header),
        }
        antenna = antennas.get(spec.channel)
        if antenna:
            glob["antenna:model"] = antenna
        geo = ctx.get("geolocation")
        if geo:
            glob["core:geolocation"] = geo
        meta = {"global": glob, "captures": captures, "annotations": annotations}
        meta_path = path / f"{spec.name}.sigmf-meta"
        _atomic_write_json(meta_path, meta)
        meta_paths[spec.name] = meta_path

    collection = {
        "collection": {
            "core:version": sigmf.__specification__,
            "core:description": "reAPET session: one recording per antenna, sample-aligned",
            "core:extensions": EXTENSIONS,
            "core:streams": [
                {"name": name, "hash": _sha512(p, p.stat().st_size)}
                for name, p in meta_paths.items()
            ],
            "reapet:antennas": antennas,
            "reapet:state": "closed" if close else "recording",
        }
    }
    _atomic_write_json(path / f"{COLLECTION}.sigmf-collection", collection)
    return {"collection": path / f"{COLLECTION}.sigmf-collection", "meta": meta_paths}


def recover(path: Path, t_ns: int | None = None) -> dict:
    """Make an interrupted session valid: whole samples, equal lengths, metadata rebuilt."""
    path = Path(path)
    jpath = path / JOURNAL
    raw = jpath.read_bytes()
    if raw and not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n") + 1
        with open(jpath, "r+b") as f:
            f.truncate(cut)
    records = read_journal(path)
    header = records[0]
    streams = [StreamSpec(**s) for s in header["streams"]]
    for kind in {s.kind for s in streams}:
        group = [s for s in streams if s.kind == kind]
        sizes = []
        for s in group:
            p = path / f"{s.name}.sigmf-data"
            sizes.append(p.stat().st_size // s.sample_size if p.exists() else 0)
        n = min(sizes)
        for s in group:
            p = path / f"{s.name}.sigmf-data"
            if p.exists():
                with open(p, "r+b") as f:
                    f.truncate(n * s.sample_size)
    bpath = path / BLOCKS
    if bpath.exists():
        size = bpath.stat().st_size
        with open(bpath, "r+b") as f:
            f.truncate(size - size % BLOCK_DTYPE.itemsize)
    if not any(r["type"] == "close" for r in records):
        if t_ns is None:
            t_ns = int(dt.datetime.now(dt.UTC).timestamp() * 1e9)
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "close",
                        "reason": "abnormal_close",
                        "counter_end": None,
                        "t_ns": t_ns,
                        "recovered": True,
                    }
                )
                + "\n"
            )
    return build_metadata(path)


def read_blocks(path: Path) -> np.ndarray:
    return np.fromfile(Path(path) / BLOCKS, dtype=BLOCK_DTYPE)
