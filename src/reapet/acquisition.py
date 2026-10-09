"""Acquisition: callback queue, pairing of the two receivers by counter, writer loop.

The device callbacks only copy samples into a preallocated ring per receiver
and enqueue a small record (KTD8). A writer thread pairs the two receivers by
sample counter, opens a new segment on both recordings at every gap (KTD5),
tracks saturation and overload per receiver (KTD7), decimates to the narrow
slice (KTD6) and hands everything to the session.
"""

from __future__ import annotations

import collections
import errno
import math
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .device import (
    CHANNELS,
    EVENT_FAILURE,
    EVENT_OVERLOAD_OFF,
    EVENT_OVERLOAD_ON,
    EVENT_REMOVED,
)
from .dsp import CLIP_FRACTION, Decimator, IntervalTracker, block_stats
from .session import BLOCK_DTYPE, Session

FLAG_RESET = 1


@dataclass
class Block:
    channel: int
    counter: int
    n: int
    t_ns: int
    offset: int  # position in the ring
    flags: int = 0
    data: np.ndarray | None = None


@dataclass
class Event:
    channel: int | None
    kind: str
    t_ns: int


class BlockQueue:
    """Sink for the device: one ring of int16 I/Q per receiver plus a FIFO of records.

    ``push_block`` never blocks: when the ring has no room the block is dropped,
    and the counter discontinuity it leaves becomes a declared gap.
    """

    def __init__(self, capacity_samples: int, channels: int = 2):
        self.capacity = capacity_samples
        self.rings = [np.zeros((capacity_samples, 2), np.int16) for _ in range(channels)]
        self.write_pos = [0] * channels  # producer side
        self.read_pos = [0] * channels  # consumer side
        self.fifo: queue.SimpleQueue = queue.SimpleQueue()
        self.dropped: collections.deque = collections.deque(maxlen=10000)
        self.dropped_blocks = [0] * channels
        self.reset_flags = [0] * channels

    def push_block(self, channel, first_sample, i, q, t_ns, flags: int = 0) -> None:
        n = len(i)
        wp = self.write_pos[channel]
        if wp + n - self.read_pos[channel] > self.capacity:
            self.dropped.append((channel, first_sample, n))
            self.dropped_blocks[channel] += 1
            return
        ring = self.rings[channel]
        start = wp % self.capacity
        first = min(n, self.capacity - start)
        ring[start : start + first, 0] = i[:first]
        ring[start : start + first, 1] = q[:first]
        if first < n:
            ring[: n - first, 0] = i[first:]
            ring[: n - first, 1] = q[first:]
        self.write_pos[channel] = wp + n
        self.fifo.put(Block(channel, first_sample, n, t_ns, wp, flags))

    def push_event(self, channel, kind, t_ns) -> None:
        self.fifo.put(Event(channel, kind, t_ns))

    def get(self, timeout: float):
        try:
            item = self.fifo.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, Block):
            start = item.offset % self.capacity
            if start + item.n <= self.capacity:
                item.data = self.rings[item.channel][start : start + item.n]
            else:
                ring = self.rings[item.channel]
                item.data = np.concatenate((ring[start:], ring[: item.n - (self.capacity - start)]))
        return item

    def release(self, block: Block) -> None:
        self.read_pos[block.channel] = block.offset + block.n

    def drain(self) -> None:
        while True:
            item = self.get(0)
            if item is None:
                return
            if isinstance(item, Block):
                self.release(item)

    def was_dropped(self, channel: int, start: int, end: int) -> bool:
        return any(c == channel and s < end and s + n > start for c, s, n in list(self.dropped))


@dataclass
class ChannelStatus:
    saturation_intervals: int = 0
    saturation_open: bool = False
    overload_intervals: int = 0
    overload_open: bool = False
    clipped_samples: int = 0
    last_peak_dbfs: float = -math.inf


@dataclass
class Status:
    recording: bool = False
    seconds: float = 0.0
    gaps: int = 0
    dropped_blocks: int = 0
    disk_free_bytes: int | None = None
    close_reason: str | None = None
    channels: list = field(default_factory=lambda: [ChannelStatus(), ChannelStatus()])


@dataclass
class RecorderConfig:
    fs: float
    full_scale: int
    decimation_factor: int
    shift_hz: int
    taps: np.ndarray
    store_wide: bool = False
    clip_fraction: float = CLIP_FRACTION
    saturation_hold_s: float = 1.0
    disconnect_timeout_s: float = 3.0
    disk_check_s: float = 2.0
    disk_margin_s: float = 120.0
    disk_margin_min_bytes: int = 1 << 30
    sync_s: float = 2.0
    flush_samples: int = 1 << 16


class Recorder:
    """The writer: consumes the queue and writes the session."""

    def __init__(
        self,
        session: Session,
        q: BlockQueue,
        cfg: RecorderConfig,
        *,
        clock=time.monotonic,
        disk_usage=shutil.disk_usage,
        before_close=None,
    ):
        self.session = session
        self.before_close = before_close  # e.g. the final clock check
        self.q = q
        self.cfg = cfg
        self.clock = clock
        self.disk_usage = disk_usage
        self.status = Status(recording=True)
        self.decimators = [
            Decimator(cfg.fs, cfg.decimation_factor, cfg.shift_hz, cfg.taps, cfg.full_scale)
            for _ in CHANNELS
        ]
        hold = int(cfg.saturation_hold_s * cfg.fs)
        self.sat = [IntervalTracker(hold) for _ in CHANNELS]
        self.overload_start: list[int | None] = [None, None]
        self.pending: list[collections.deque] = [collections.deque(), collections.deque()]
        self.front_offset = [0, 0]  # samples already consumed from the front block
        self.cursor: int | None = None  # next counter to emit on both receivers
        self.last_counter = [None, None]  # end of the last block seen per receiver
        self.started = False
        self.closed = False
        self.first_counter: int | None = None
        self.narrow_written = 0
        self.wide_written = 0
        self._stage: list[tuple[int, np.ndarray, np.ndarray]] = []
        self._stage_n = 0
        self._block_rows: list[tuple] = []
        now = clock()
        self.last_block_time = now
        self._next_disk = now
        self._next_sync = now + cfg.sync_s
        bytes_per_s = 2 * cfg.fs / cfg.decimation_factor * 8
        if cfg.store_wide:
            bytes_per_s += 2 * cfg.fs * 4
        self.disk_margin = max(cfg.disk_margin_min_bytes, int(cfg.disk_margin_s * bytes_per_s))
        self.narrow_names = [f"rx-{c}" for c in CHANNELS]
        self.wide_names = [f"rx-{c}-wide" for c in CHANNELS]

    # --- main loop ---------------------------------------------------------------

    def run(self, stop: threading.Event, on_status=None, status_every_s: float = 1.0) -> str:
        next_status = self.clock()
        while not self.closed:
            if stop.is_set():
                self.close("stop")
                break
            self.step(0.1)
            if on_status and self.clock() >= next_status:
                next_status = self.clock() + status_every_s
                on_status(self.status)
        if on_status:
            on_status(self.status)
        return self.status.close_reason

    def step(self, timeout: float) -> None:
        """Process one queued item, then the periodic checks."""
        try:
            item = self.q.get(timeout)
            if item is not None:
                if isinstance(item, Block):
                    self._on_block(item)
                else:
                    self._on_event(item)
            if self.closed:
                return
            now = self.clock()
            if now - self.last_block_time > self.cfg.disconnect_timeout_s:
                self.close(
                    "disconnection", detail={"no_data_for_s": round(now - self.last_block_time, 3)}
                )
                return
            if now >= self._next_disk:
                self._next_disk = now + self.cfg.disk_check_s
                free = self.disk_usage(self.session.path).free
                self.status.disk_free_bytes = free
                if free < self.disk_margin:
                    self.close(
                        "disk_limit", detail={"free_bytes": free, "margin_bytes": self.disk_margin}
                    )
                    return
            if now >= self._next_sync:
                self._next_sync = now + self.cfg.sync_s
                self._flush_blocks()
                self.session.sync()
        except OSError as e:
            if self.closed:
                raise
            reason = "disk_full" if e.errno == errno.ENOSPC else "disk_error"
            self.close(reason, detail={"error": str(e)})

    # --- input -------------------------------------------------------------------

    def _on_event(self, ev: Event) -> None:
        if ev.kind in (EVENT_REMOVED, EVENT_FAILURE):
            self.close("disconnection", detail={"event": ev.kind})
            return
        ch = ev.channel
        pos = self.last_counter[ch] if ch is not None else None
        if pos is None:
            pos = self.cursor if self.cursor is not None else 0
        if ev.kind == EVENT_OVERLOAD_ON and self.overload_start[ch] is None:
            self.overload_start[ch] = pos
            self.status.channels[ch].overload_open = True
            self.session.journal(
                {
                    "type": "interval_open",
                    "channel": CHANNELS[ch],
                    "kind": "overload",
                    "counter_start": pos,
                    "t_ns": ev.t_ns,
                }
            )
        elif ev.kind == EVENT_OVERLOAD_OFF and self.overload_start[ch] is not None:
            self._close_interval(ch, "overload", self.overload_start[ch], pos)
            self.overload_start[ch] = None
            self.status.channels[ch].overload_open = False

    def _close_interval(self, ch: int, kind: str, start: int, end: int, **extra) -> None:
        self.session.journal(
            {
                "type": "interval",
                "channel": CHANNELS[ch],
                "kind": kind,
                "counter_start": start,
                "counter_end": end,
                **extra,
            }
        )
        st = self.status.channels[ch]
        if kind == "saturation":
            st.saturation_intervals += 1
        else:
            st.overload_intervals += 1

    def _on_block(self, b: Block) -> None:
        ch = b.channel
        self.last_block_time = self.clock()
        if b.flags & FLAG_RESET and self.started:
            self.q.release(b)
            self.close("stream_reset", detail={"channel": CHANNELS[ch]})
            return
        end = b.counter + b.n
        self.last_counter[ch] = end
        peak, power, clipped = block_stats(b.data, self.cfg.full_scale, self.cfg.clip_fraction)
        self._block_rows.append((ch, b.flags, b.n, b.counter, b.t_ns, peak, power, clipped))
        st = self.status.channels[ch]
        st.last_peak_dbfs = peak
        st.clipped_samples += clipped
        tracker = self.sat[ch]
        was_open = tracker.is_open
        closed = tracker.update(b.counter, end, clipped > 0)
        if tracker.is_open and not was_open:
            self.session.journal(
                {
                    "type": "interval_open",
                    "channel": CHANNELS[ch],
                    "kind": "saturation",
                    "counter_start": tracker.start,
                    "t_ns": b.t_ns,
                }
            )
        if closed:
            self._close_interval(ch, "saturation", *closed)
        st.saturation_open = tracker.is_open
        self.pending[ch].append(b)
        self._pair()

    # --- pairing (KTD5) -----------------------------------------------------------

    def _trim(self, ch: int) -> None:
        dq = self.pending[ch]
        while dq:
            b = dq[0]
            start = b.counter + self.front_offset[ch]
            end = b.counter + b.n
            if end <= self.cursor:
                dq.popleft()
                self.front_offset[ch] = 0
                self.q.release(b)
            else:
                if start < self.cursor:
                    self.front_offset[ch] = self.cursor - b.counter
                return

    def _front_start(self, ch: int) -> int:
        return self.pending[ch][0].counter + self.front_offset[ch]

    def _pair(self) -> None:
        while self.pending[0] and self.pending[1] and not self.closed:
            if self.cursor is None:
                self.cursor = max(self._front_start(0), self._front_start(1))
                self.first_counter = self.cursor
                self._begin_segment(self.cursor)
                self.started = True
            self._trim(0)
            self._trim(1)
            if not (self.pending[0] and self.pending[1]):
                return
            s0, s1 = self._front_start(0), self._front_start(1)
            s = max(s0, s1)
            if s > self.cursor:
                missing = [CHANNELS[c] for c, sc in ((0, s0), (1, s1)) if sc > self.cursor]
                dropped = any(
                    self.q.was_dropped(CHANNELS.index(c), self.cursor, s) for c in missing
                )
                self.session.journal(
                    {
                        "type": "gap",
                        "counter_start": self.cursor,
                        "counter_end": s,
                        "channels": missing,
                        "reason": "queue_full" if dropped else "counter_discontinuity",
                    }
                )
                self.status.gaps += 1
                self.cursor = s
                self._begin_segment(s)
                continue
            b0, b1 = self.pending[0][0], self.pending[1][0]
            m = min(b0.counter + b0.n, b1.counter + b1.n) - self.cursor
            o0, o1 = self.front_offset[0], self.front_offset[1]
            self._stage.append(
                (self.cursor, b0.data[o0 : o0 + m].copy(), b1.data[o1 : o1 + m].copy())
            )
            self._stage_n += m
            self.cursor += m
            self._trim(0)
            self._trim(1)
            if self._stage_n >= self.cfg.flush_samples:
                self._flush_stage()

    def _segment_time(self, counter: int) -> int:
        for b in (*self.pending[0], *self.pending[1]):
            if b.counter <= counter < b.counter + b.n:
                return b.t_ns + int((counter - b.counter) / self.cfg.fs * 1e9)
        return time.time_ns()

    def _begin_segment(self, counter: int) -> None:
        self._flush_stage()
        g0 = 0
        for d in self.decimators:
            g0 = d.reset(counter)
        self.session.journal(
            {
                "type": "segment",
                "counter": counter,
                "g0": g0,
                "narrow_index": self.narrow_written,
                "wide_index": self.wide_written,
                "t_ns": self._segment_time(counter),
            }
        )

    def _flush_stage(self) -> None:
        if not self._stage:
            return
        stage, self._stage, self._stage_n = self._stage, [], 0
        counter = stage[0][0]
        a = np.concatenate([s[1] for s in stage]) if len(stage) > 1 else stage[0][1]
        b = np.concatenate([s[2] for s in stage]) if len(stage) > 1 else stage[0][2]
        if self.cfg.store_wide:
            self.session.write(self.wide_names[0], a)
            self.session.write(self.wide_names[1], b)
            self.wide_written += len(a)
        ya = self.decimators[0].process(a, counter)
        yb = self.decimators[1].process(b, counter)
        self.session.write(self.narrow_names[0], ya)
        self.session.write(self.narrow_names[1], yb)
        self.narrow_written += len(ya)
        self.status.seconds = (counter + len(a) - self.first_counter) / self.cfg.fs

    def _flush_blocks(self) -> None:
        if self._block_rows:
            rows = np.array(self._block_rows, dtype=BLOCK_DTYPE)
            self._block_rows = []
            self.session.add_blocks(rows)
        self.status.dropped_blocks = sum(self.q.dropped_blocks)

    # --- close -------------------------------------------------------------------

    def close(self, reason: str, detail: dict | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        end = self.cursor
        try:
            self._flush_stage()
            self._flush_blocks()
        except OSError as e:
            detail = dict(detail or {}, write_error=str(e))
        for ch in range(len(CHANNELS)):
            last = self.last_counter[ch] if self.last_counter[ch] is not None else end
            iv = self.sat[ch].flush()
            if iv:
                self._close_interval(ch, "saturation", *iv, closed_by="session_end")
            if self.overload_start[ch] is not None:
                self._close_interval(
                    ch, "overload", self.overload_start[ch], last, closed_by="session_end"
                )
                self.overload_start[ch] = None
        self.status.recording = False
        self.status.close_reason = reason
        self.status.dropped_blocks = sum(self.q.dropped_blocks)
        if self.before_close is not None:
            try:
                self.before_close()
            except Exception as e:  # closing the session matters more
                detail = dict(detail or {}, before_close_error=str(e))
        self.session.close(reason, end, time.time_ns(), detail)
