"""Simulated dual-receiver device (KTD13).

It produces noise plus tones on both receivers with a sample counter, and can
inject clipping, overload events, counter gaps, a stream that stops and a
removed-device event. The signal is a function of the absolute sample index, so
both receivers see the same signal as through a splitter, and a block always
continues the previous one exactly.

Levels are given in dBFS at the highest gain (``gain_steps()[0]``); every dB of
extra gain reduction lowers them by one dB.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace

import numpy as np

from .device import (
    EVENT_OVERLOAD_OFF,
    EVENT_OVERLOAD_ON,
    EVENT_REMOVED,
    Capabilities,
    Device,
    DeviceError,
    DeviceInfo,
    GainStep,
    Sink,
    TunerConfig,
    TunerReadback,
)

FULL_SCALE = 32767


@dataclass(frozen=True)
class Tone:
    offset_hz: float  # from the tuner centre
    dbfs: float  # peak level at the highest gain
    channels: tuple[int, ...] = (0, 1)


@dataclass
class FakeScenario:
    receivers: int = 2
    same_clock: bool = True
    sample_counter: bool = True
    agc_can_disable: bool = True
    manual_gain: bool = True
    overload_events: bool = True
    inputs: tuple[tuple[str, ...], ...] = (("50ohm", "hiz"), ("50ohm",))
    block_size: int = 2048
    noise_dbfs: float = -45.0  # per component, at the highest gain
    tones: tuple[Tone, ...] = ()
    level_offset_db: tuple[float, float] = (0.0, 0.0)  # per receiver
    seed: int = 1
    # (channel, start_s, duration_s): a tone at +6 dBFS that clips regardless of gain
    clipping: tuple[tuple[int, float, float], ...] = ()
    # (channel, start_s, duration_s): overload events from the "device"
    overload: tuple[tuple[int, float, float], ...] = ()
    # (channel, at_s, n_samples): the counter of that channel jumps
    counter_gaps: tuple[tuple[int, float, int], ...] = ()
    # the stream stops producing at this time (seconds of samples)
    stop_at_s: float | None = None
    # a device-removed event is pushed at this time
    removed_at_s: float | None = None
    # extra readback differences on receiver B, e.g. {"if_gr_db": 1}
    readback_offset_b: dict = field(default_factory=dict)
    # overload is reported when the peak at the current gain exceeds this (dBFS); None = never
    overload_above_dbfs: float | None = None
    # deliver the two receivers' blocks in swapped order
    swap_order: bool = False


class FakeDevice(Device):
    def __init__(self, scenario: FakeScenario | None = None, *, speed: float = 1.0):
        super().__init__()
        self.scenario = scenario or FakeScenario()
        self.speed = speed  # >1 runs faster than real time; float("inf") does not sleep
        self._config: TunerConfig | None = None
        self._gain: GainStep | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sink: Sink | None = None
        self._cursor = [0] * self.scenario.receivers
        self._gaps_done: set[int] = set()
        self._removed_sent = False
        self._overload_state = [False] * self.scenario.receivers
        self._rng = np.random.default_rng(self.scenario.seed)
        self.t0_ns = 1_700_000_000_000_000_000

    # --- description -------------------------------------------------------------

    def info(self) -> DeviceInfo:
        return DeviceInfo(
            name="Simulated dual receiver",
            serial="SIM0001",
            driver="reapet-fake",
            driver_version="1",
        )

    def capabilities(self) -> Capabilities:
        s = self.scenario
        return Capabilities(
            receivers=s.receivers,
            same_clock=s.same_clock,
            sample_counter=s.sample_counter,
            agc_can_disable=s.agc_can_disable,
            manual_gain=s.manual_gain,
            overload_events=s.overload_events,
            sample_rates=(2_000_000.0,),
            native_format="ci16_le",
            full_scale=FULL_SCALE,
            inputs=s.inputs[: s.receivers],
        )

    def gain_steps(self, center_hz: float, input_name: str) -> list[GainStep]:
        return [
            GainStep(lna_state=0, if_gr_db=gr, total_gr_db=float(gr)) for gr in range(20, 60, 3)
        ]

    # --- settings ----------------------------------------------------------------

    def configure(self, config: TunerConfig) -> None:
        self._check_unlocked()
        if config.input not in self.scenario.inputs[0]:
            raise DeviceError(f"input {config.input!r} not available")
        self._config = config
        self._gain = config.gain

    def set_gain(self, step: GainStep) -> None:
        self._check_unlocked()
        self._gain = step

    def readback(self) -> list[TunerReadback]:
        if self._config is None or self._gain is None:
            raise DeviceError("device not configured")
        out = []
        for ch, name in enumerate(("A", "B")[: self.scenario.receivers]):
            rb = TunerReadback(
                channel=name,
                center_hz=self._config.center_hz,
                sample_rate=self._config.sample_rate,
                bandwidth_hz=self._config.bandwidth_hz,
                lna_state=self._gain.lna_state,
                if_gr_db=self._gain.if_gr_db,
                agc_enabled=False,
                input=self._config.input,
                extra={"total_gr_db": self._gain.total_gr_db},
            )
            if ch == 1 and self.scenario.readback_offset_b:
                changes = {
                    k: getattr(rb, k) + v for k, v in self.scenario.readback_offset_b.items()
                }
                rb = replace(rb, **changes)
            out.append(rb)
        return out

    # --- streaming ---------------------------------------------------------------

    @property
    def fs(self) -> float:
        return self._config.sample_rate if self._config else 2_000_000.0

    def _gain_db(self) -> float:
        ref = self.gain_steps(0, "")[0].total_gr_db
        return -((self._gain.total_gr_db if self._gain else ref) - ref)

    def _samples(self, ch: int, start: int, n: int) -> np.ndarray:
        s = self.scenario
        fs = self.fs
        idx = start + np.arange(n)
        level = self._gain_db() + s.level_offset_db[ch]
        sigma = FULL_SCALE * 10 ** ((s.noise_dbfs + level) / 20)
        x = self._rng.normal(0, sigma, n) + 1j * self._rng.normal(0, sigma, n)
        for tone in s.tones:
            if ch in tone.channels:
                amp = FULL_SCALE * 10 ** ((tone.dbfs + level) / 20)
                x += amp * np.exp(2j * np.pi * tone.offset_hz * idx / fs)
        for c, t0, dur in s.clipping:
            if c == ch:
                a, b = int(t0 * fs), int((t0 + dur) * fs)
                sel = (idx >= a) & (idx < b)
                if sel.any():
                    x[sel] += 2 * FULL_SCALE * np.exp(2j * np.pi * 10e3 * idx[sel] / fs)
        return x

    def make_block(self, ch: int) -> tuple[int, np.ndarray, np.ndarray]:
        """Produce the next block of receiver ``ch``: (first_sample, i, q)."""
        s = self.scenario
        start = self._cursor[ch]
        for k, (c, at_s, n_skip) in enumerate(s.counter_gaps):
            if c == ch and k not in self._gaps_done and start >= int(at_s * self.fs):
                self._gaps_done.add(k)
                start += n_skip
        x = self._samples(ch, start, s.block_size)
        i = np.clip(np.round(x.real), -FULL_SCALE - 1, FULL_SCALE).astype(np.int16)
        q = np.clip(np.round(x.imag), -FULL_SCALE - 1, FULL_SCALE).astype(np.int16)
        self._cursor[ch] = start + s.block_size
        return start, i, q

    def _events_for(self, ch: int, start: int, end: int, sink: Sink) -> None:
        s = self.scenario
        fs = self.fs
        t_ns = self.t0_ns + int(end / fs * 1e9)
        wanted = None
        for c, t0, dur in s.overload:
            if c == ch:
                wanted = bool(wanted) or (int(t0 * fs) < end and int((t0 + dur) * fs) > start)
        if s.overload_above_dbfs is not None:
            peak = max(t.dbfs for t in s.tones) if s.tones else s.noise_dbfs + 12
            wanted = bool(wanted) or (
                peak + self._gain_db() + s.level_offset_db[ch] > s.overload_above_dbfs
            )
        if wanted is None:
            return
        if wanted != self._overload_state[ch]:
            self._overload_state[ch] = wanted
            sink.push_event(ch, EVENT_OVERLOAD_ON if wanted else EVENT_OVERLOAD_OFF, t_ns)

    def produce(self, sink: Sink, n_blocks: int) -> bool:
        """Push ``n_blocks`` blocks per receiver synchronously. False once the stream ended."""
        s = self.scenario
        order = list(range(s.receivers))
        if s.swap_order:
            order.reverse()
        for _ in range(n_blocks):
            pos = min(self._cursor)
            if (
                s.removed_at_s is not None
                and not self._removed_sent
                and pos >= s.removed_at_s * self.fs
            ):
                self._removed_sent = True
                sink.push_event(None, EVENT_REMOVED, self.t0_ns + int(pos / self.fs * 1e9))
                return False
            if s.stop_at_s is not None and pos >= s.stop_at_s * self.fs:
                return False
            for ch in order:
                first, i, q = self.make_block(ch)
                end = first + len(i)
                if s.overload_events:
                    self._events_for(ch, first, end, sink)
                sink.push_block(ch, first, i, q, self.t0_ns + int(first / self.fs * 1e9))
        return True

    def start(self, sink: Sink) -> None:
        if self._config is None:
            raise DeviceError("device not configured")
        self._sink = sink
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="fake-device", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        t_start = time.monotonic()
        produced = 0
        block_s = self.scenario.block_size / self.fs
        while not self._stop.is_set():
            if not self.produce(self._sink, 1):
                self._stop.wait()  # silent, like a dead USB link
                break
            produced += 1
            if self.speed != float("inf"):
                ahead = produced * block_s / self.speed - (time.monotonic() - t_start)
                if ahead > 0:
                    time.sleep(ahead)
            elif produced % 64 == 0:
                time.sleep(0)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def close(self) -> None:
        self.stop()

    def counter_info(self) -> dict:
        return {"counter_bits": 64, "counter_step": 1}
