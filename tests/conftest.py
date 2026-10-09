from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from reapet.acquisition import BlockQueue, Recorder, RecorderConfig
from reapet.bands import BANDS, NARROW_PASSBAND_HZ
from reapet.device import TunerConfig
from reapet.dsp import design_lowpass
from reapet.fake_device import FakeDevice, FakeScenario
from reapet.session import Session, StreamSpec

FS = 2_000_000
FACTOR = 32
SHIFT = 200_000
TAPS = design_lowpass(FS, FACTOR, NARROW_PASSBAND_HZ)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Harness:
    """A fake device feeding a recorder synchronously, with a controllable clock."""

    def __init__(
        self,
        path: Path,
        scenario: FakeScenario,
        *,
        store_wide=False,
        cfg_overrides=None,
        disk_free=10**12,
    ):
        band = BANDS["20m"]
        self.dev = FakeDevice(scenario, speed=float("inf"))
        steps = self.dev.gain_steps(0, "50ohm")
        self.dev.configure(TunerConfig(band.tuner_center_hz, FS, 1_536_000, steps[0], "50ohm"))
        self.dev.lock()
        self.q = BlockQueue(FS * 4)
        streams = [
            StreamSpec(f"rx-{c}", c, "narrow", "cf32_le", FS / FACTOR, 14_000_000) for c in "AB"
        ]
        if store_wide:
            streams += [
                StreamSpec(f"rx-{c}-wide", c, "wide", "ci16_le", FS, 13_800_000) for c in "AB"
            ]
        header = {
            "context": {
                "antennas": {"A": "loop", "B": "dipole"},
                "locator": None,
                "geolocation": None,
                "missing": ["locator"],
            },
            "decimation": {"factor": FACTOR, "taps": len(TAPS), "shift_hz": SHIFT},
        }
        self.session = Session(path, header, streams)
        self.clock = FakeClock()
        self.disk_free = disk_free
        cfg = dict(
            fs=FS,
            full_scale=32767,
            decimation_factor=FACTOR,
            shift_hz=SHIFT,
            taps=TAPS,
            store_wide=store_wide,
            disk_check_s=0.5,
            sync_s=0.5,
            disk_margin_min_bytes=1 << 20,
            flush_samples=1 << 15,
        )
        cfg.update(cfg_overrides or {})
        self.rec = Recorder(
            self.session,
            self.q,
            RecorderConfig(**cfg),
            clock=self.clock,
            disk_usage=lambda p: type("U", (), {"free": self.disk_free})(),
        )

    def drain(self):
        while not self.rec.closed and not self.q.fifo.empty():
            self.rec.step(0)

    def run_seconds(self, seconds: float, step_s: float = 0.05):
        """Produce ``seconds`` of samples, advancing the fake clock in real-time steps."""
        blocks_per_step = max(1, int(step_s * FS / self.dev.scenario.block_size))
        produced = 0.0
        while produced < seconds and not self.rec.closed:
            alive = self.dev.produce(self.q, blocks_per_step)
            produced += blocks_per_step * self.dev.scenario.block_size / FS
            self.clock.t += blocks_per_step * self.dev.scenario.block_size / FS
            self.drain()
            if not self.rec.closed:
                self.rec.step(0)
            if not alive:
                return False
        return True

    def idle(self, seconds: float, step_s: float = 0.25):
        t_end = self.clock.t + seconds
        while self.clock.t < t_end and not self.rec.closed:
            self.clock.t += step_s
            self.rec.step(0)


@pytest.fixture
def harness(tmp_path):
    def make(scenario=None, **kw):
        return Harness(tmp_path / "session", scenario or FakeScenario(), **kw)

    return make


def read_cf32(path: Path) -> np.ndarray:
    return np.fromfile(path, dtype=np.complex64)
