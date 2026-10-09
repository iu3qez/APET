"""Headroom check and gain proposal (R3, KTD12).

With the device streaming, the gain is stepped from the highest down. For each
step a short capture measures the wide-band peak of both receivers, clipped
samples and overload events. The first step that leaves ``margin_db`` below
full scale on both receivers, with no clipping and no overload, is chosen; it is
applied equally to both tuners. The thresholds are provisional until tuned on
the RSPduo (U6 verification).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .acquisition import Block, BlockQueue
from .device import EVENT_OVERLOAD_OFF, EVENT_OVERLOAD_ON, Device, DeviceError, GainStep
from .dsp import CLIP_FRACTION, block_stats

DEFAULT_MARGIN_DB = 10.0
SETTLE_S = 0.2
MEASURE_S = 0.5


@dataclass
class GainProposal:
    step: GainStep
    margin_met: bool
    margin_db: float
    measurements: list[dict]

    def as_dict(self) -> dict:
        return {
            "step": asdict(self.step),
            "margin_met": self.margin_met,
            "margin_db": self.margin_db,
            "measurements": self.measurements,
        }


def _measure(
    q: BlockQueue,
    fs: float,
    full_scale: int,
    overload_state: list[bool],
    settle_s: float,
    measure_s: float,
    pump: Callable[[], None] | None,
    timeout_s: float,
) -> dict:
    """Discard ``settle_s`` of samples, then measure ``measure_s`` on both receivers."""
    skip = int(settle_s * fs)
    need = int(measure_s * fs)
    seen = [0, 0]
    measured = [0, 0]
    peak = [-math.inf, -math.inf]
    clipped = [0, 0]
    overload_seen = list(overload_state)
    deadline = time.monotonic() + timeout_s
    while min(measured) < need:
        item = q.get(0.05)
        if item is None:
            if pump is not None:
                pump()
            elif time.monotonic() > deadline:
                raise DeviceError("no samples from the device during the headroom check")
            continue
        if not isinstance(item, Block):
            if item.channel is not None and item.kind in (EVENT_OVERLOAD_ON, EVENT_OVERLOAD_OFF):
                overload_state[item.channel] = item.kind == EVENT_OVERLOAD_ON
                overload_seen[item.channel] |= overload_state[item.channel]
            continue
        ch = item.channel
        if seen[ch] >= skip:
            p, _, c = block_stats(item.data, full_scale, CLIP_FRACTION)
            peak[ch] = max(peak[ch], p)
            clipped[ch] += c
            measured[ch] += item.n
        seen[ch] += item.n
        q.release(item)
    return {
        "peak_dbfs": [round(p, 2) for p in peak],
        "clipped": clipped,
        "overload": [bool(o) for o in overload_seen],
    }


def propose_gain(
    device: Device,
    q: BlockQueue,
    steps: list[GainStep],
    *,
    fs: float,
    full_scale: int,
    margin_db: float = DEFAULT_MARGIN_DB,
    settle_s: float = SETTLE_S,
    measure_s: float = MEASURE_S,
    pump: Callable[[], None] | None = None,
    timeout_s: float = 5.0,
) -> GainProposal:
    """Choose the highest gain keeping the margin on both receivers (device streaming)."""
    if not steps:
        raise DeviceError("the device offers no gain steps")
    overload_state = [False, False]
    measurements = []
    for step in steps:
        device.set_gain(step)
        m = _measure(q, fs, full_scale, overload_state, settle_s, measure_s, pump, timeout_s)
        m["step"] = asdict(step)
        ok = max(m["peak_dbfs"]) <= -margin_db and not any(m["clipped"]) and not any(m["overload"])
        m["margin_met"] = ok
        measurements.append(m)
        if ok:
            return GainProposal(step, True, margin_db, measurements)
    return GainProposal(steps[-1], False, margin_db, measurements)
