"""Device interface shared by every backend (SDRplay API, simulated device).

A device offers two receivers ("tuners") that sample on one clock. The recorder
configures both identically, proposes a gain, locks the settings and reads them
back from each tuner separately. Samples reach the recorder through a ``Sink``
(the acquisition queue); the device never processes them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Protocol

import numpy as np

CHANNELS = ("A", "B")

# Event kinds a backend may push to the sink.
EVENT_OVERLOAD_ON = "overload_on"
EVENT_OVERLOAD_OFF = "overload_off"
EVENT_REMOVED = "device_removed"
EVENT_FAILURE = "device_failure"


class DeviceError(Exception):
    """A device operation failed."""


class LockedError(DeviceError):
    """A setting was changed after the device was locked."""


class ReadbackMismatch(DeviceError):
    """The two tuners read back different settings."""

    def __init__(self, differences: list[str]):
        super().__init__("tuners differ after lock: " + "; ".join(differences))
        self.differences = differences


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    serial: str
    driver: str
    driver_version: str


@dataclass(frozen=True)
class GainStep:
    """One gain setting, applied equally to both tuners.

    ``total_gr_db`` is the total gain reduction (LNA plus IF); a lower value
    means more gain.
    """

    lna_state: int
    if_gr_db: int
    total_gr_db: float


@dataclass(frozen=True)
class Capabilities:
    receivers: int
    same_clock: bool
    sample_counter: bool
    agc_can_disable: bool
    manual_gain: bool
    overload_events: bool
    sample_rates: tuple[float, ...]
    native_format: str
    full_scale: int
    # Input types available on each receiver, in order of preference.
    inputs: tuple[tuple[str, ...], ...]


def missing_capabilities(caps: Capabilities) -> list[str]:
    """Return the capabilities required by R14 that the device lacks."""
    missing = []
    if caps.receivers < 2:
        missing.append(f"two receivers (device has {caps.receivers})")
    if caps.receivers >= 2 and not (caps.same_clock and caps.sample_counter):
        missing.append("simultaneous reception on one clock with a sample counter")
    if not caps.agc_can_disable:
        missing.append("AGC that can be disabled")
    if not caps.manual_gain:
        missing.append("manual gain")
    if caps.receivers >= 2 and common_input(caps) is None:
        missing.append("an input type available on both receivers")
    return missing


def common_input(caps: Capabilities) -> str | None:
    """The first input type, in the first receiver's order, present on every receiver."""
    if not caps.inputs:
        return None
    shared = set(caps.inputs[0]).intersection(*caps.inputs[1:])
    for name in caps.inputs[0]:
        if name in shared:
            return name
    return None


@dataclass(frozen=True)
class TunerConfig:
    """Settings requested for both tuners."""

    center_hz: float
    sample_rate: float
    bandwidth_hz: float
    gain: GainStep
    input: str


@dataclass(frozen=True)
class TunerReadback:
    """Settings read back from one tuner after locking."""

    channel: str
    center_hz: float
    sample_rate: float
    bandwidth_hz: float
    lna_state: int
    if_gr_db: int
    agc_enabled: bool
    input: str
    extra: dict = field(default_factory=dict)  # compared between tuners
    reported: dict = field(default_factory=dict)  # recorded only (e.g. calibrated gain)

    def as_dict(self) -> dict:
        return asdict(self)


# Fields that must be identical on the two tuners for the chains to be equivalent.
_COMPARED_FIELDS = (
    "center_hz",
    "sample_rate",
    "bandwidth_hz",
    "lna_state",
    "if_gr_db",
    "agc_enabled",
    "input",
)


def readback_differences(readbacks: list[TunerReadback]) -> list[str]:
    """List the settings that differ between tuners, or that leave AGC on."""
    diffs = []
    first = readbacks[0]
    for rb in readbacks:
        if rb.agc_enabled:
            diffs.append(f"AGC is on for tuner {rb.channel}")
    for rb in readbacks[1:]:
        for name in _COMPARED_FIELDS:
            a, b = getattr(first, name), getattr(rb, name)
            if a != b and name != "agc_enabled":
                diffs.append(f"{name}: tuner {first.channel}={a!r}, tuner {rb.channel}={b!r}")
        for key in sorted(set(first.extra) | set(rb.extra)):
            a, b = first.extra.get(key), rb.extra.get(key)
            if a != b:
                diffs.append(f"{key}: tuner {first.channel}={a!r}, tuner {rb.channel}={b!r}")
    return diffs


class Sink(Protocol):
    """Receives what the device produces. Must return quickly (KTD8)."""

    def push_block(
        self, channel: int, first_sample: int, i: np.ndarray, q: np.ndarray, t_ns: int
    ) -> None: ...

    def push_event(self, channel: int | None, kind: str, t_ns: int) -> None: ...


class Device(ABC):
    """A dual-receiver device. Settings are equal on both tuners and can be locked."""

    def __init__(self) -> None:
        self._locked = False

    @property
    def locked(self) -> bool:
        return self._locked

    def _check_unlocked(self) -> None:
        if self._locked:
            raise LockedError("settings are locked for the whole session")

    @abstractmethod
    def info(self) -> DeviceInfo: ...

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def gain_steps(self, center_hz: float, input_name: str) -> list[GainStep]:
        """Available gain settings, from the highest gain to the lowest."""

    @abstractmethod
    def configure(self, config: TunerConfig) -> None:
        """Apply ``config`` to both tuners, with AGC off. Refused after lock."""

    @abstractmethod
    def set_gain(self, step: GainStep) -> None:
        """Change the gain of both tuners, also while streaming. Refused after lock."""

    @abstractmethod
    def readback(self) -> list[TunerReadback]:
        """Read the settings back from each tuner separately."""

    @abstractmethod
    def start(self, sink: Sink) -> None:
        """Start streaming both tuners into ``sink``."""

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def counter_info(self) -> dict:
        """What the backend knows about its sample counter (for the session context)."""
        return {}

    def lock(self) -> list[TunerReadback]:
        """Read back both tuners, refuse if they differ, then refuse every later change."""
        readbacks = self.readback()
        diffs = readback_differences(readbacks)
        if diffs:
            raise ReadbackMismatch(diffs)
        self._locked = True
        return readbacks
