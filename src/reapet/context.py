"""Session context: antenna names, locator, clock state (R6, R7, R8; KTD10)."""

from __future__ import annotations

import platform
import re
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable

NTP_EPOCH_OFFSET = 2_208_988_800  # seconds from 1900-01-01 to 1970-01-01
DEFAULT_NTP_SERVERS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
SYNC_TOLERANCE_S = 0.1
CLOCK_CHECK_PERIOD_S = 300.0

_LOCATOR_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")


# --- locator ---------------------------------------------------------------------


def normalize_locator(text: str) -> str | None:
    """Return the locator in canonical case (``JN65ag``), or None if invalid."""
    t = text.strip()
    if len(t) not in (4, 6):
        return None
    t = t[:2].upper() + t[2:4] + t[4:].upper()
    if not _LOCATOR_RE.match(t):
        return None
    return t[:4] + t[4:].lower()


def locator_center(locator: str) -> tuple[float, float, float, float]:
    """Centre of a 4- or 6-character Maidenhead square: (lat, lon, half_height, half_width)."""
    loc = normalize_locator(locator)
    if loc is None:
        raise ValueError(f"invalid locator: {locator!r}")
    lon = -180 + 20 * (ord(loc[0]) - ord("A")) + 2 * int(loc[2])
    lat = -90 + 10 * (ord(loc[1]) - ord("A")) + int(loc[3])
    w, h = 2.0, 1.0
    if len(loc) == 6:
        w, h = 5 / 60, 2.5 / 60
        lon += w * (ord(loc[4]) - ord("a"))
        lat += h * (ord(loc[5]) - ord("a"))
    return lat + h / 2, lon + w / 2, h / 2, w / 2


def ask_context(
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    given: dict | None = None,
) -> dict:
    """Ask for the two antenna names and the locator. Empty answers are recorded as missing.

    ``given`` holds answers already supplied (e.g. on the command line); a key
    present with an empty value counts as an empty answer and is not asked.
    """
    given = given or {}
    answers = {}
    for key, prompt in (
        ("antenna_a", "Antenna on receiver A: "),
        ("antenna_b", "Antenna on receiver B: "),
    ):
        value = given[key] if key in given else input_fn(prompt)
        answers[key] = (value or "").strip() or None
    locator = None
    raw = given.get("locator") if "locator" in given else input_fn("Locator (e.g. JN65ag): ")
    while True:
        raw = (raw or "").strip()
        if not raw:
            break
        locator = normalize_locator(raw)
        if locator:
            break
        print_fn(f"'{raw}' is not a 4- or 6-character Maidenhead locator.")
        raw = input_fn("Locator (empty to record it as missing): ")
    return build_location_context(answers["antenna_a"], answers["antenna_b"], locator)


def build_location_context(
    antenna_a: str | None, antenna_b: str | None, locator: str | None
) -> dict:
    missing = []
    if not antenna_a:
        missing.append("antenna_a")
    if not antenna_b:
        missing.append("antenna_b")
    ctx = {"antennas": {"A": antenna_a, "B": antenna_b}, "locator": locator, "geolocation": None}
    if locator:
        lat, lon, dlat, dlon = locator_center(locator)
        ctx["geolocation"] = {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}
        ctx["locator_half_size_deg"] = {"lat": dlat, "lon": dlon}
    else:
        missing.append("locator")
    ctx["missing"] = missing
    return ctx


# --- clock -----------------------------------------------------------------------


def _udp_transport(server: str, packet: bytes, timeout: float) -> tuple[bytes, int, int]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t1 = time.time_ns()
        s.sendto(packet, (server, 123))
        data, _ = s.recvfrom(512)
        t4 = time.time_ns()
    return data, t1, t4


def _ntp_to_ns(sec: int, frac: int) -> int:
    return (sec - NTP_EPOCH_OFFSET) * 1_000_000_000 + (frac * 1_000_000_000 >> 32)


def sntp_query(server: str, timeout: float = 2.0, transport=_udp_transport) -> dict:
    """One SNTP exchange. Returns offset (server minus local) and round-trip time in seconds."""
    packet = b"\x23" + bytes(47)  # LI 0, version 4, mode 3 (client)
    data, t1, t4 = transport(server, packet, timeout)
    if len(data) < 48:
        raise ValueError("short SNTP reply")
    stratum = data[1]
    t2 = _ntp_to_ns(*struct.unpack("!II", data[32:40]))
    t3 = _ntp_to_ns(*struct.unpack("!II", data[40:48]))
    if stratum == 0 or t3 <= 0:
        raise ValueError("SNTP server unsynchronised (kiss-o'-death or zero timestamp)")
    offset = ((t2 - t1) + (t3 - t4)) / 2e9
    rtt = ((t4 - t1) - (t3 - t2)) / 1e9
    return {
        "server": server,
        "offset_s": round(offset, 6),
        "rtt_s": round(rtt, 6),
        "stratum": stratum,
    }


def os_clock_status(run=subprocess.run) -> dict | None:
    """The OS view of its own clock synchronisation, if readable without privileges."""
    system = platform.system()
    try:
        if system == "Linux":
            r = run(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if r.returncode == 0:
                return {"source": "timedatectl", "synchronised": r.stdout.strip() == "yes"}
        elif system == "Windows":
            r = run(["w32tm", "/query", "/status"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                return {"source": "w32tm", "output": r.stdout.strip()[:2000]}
        elif system == "Darwin":
            # macOS exposes no unprivileged synchronisation status; record the configured server.
            r = run(
                ["/usr/sbin/systemsetup", "-getnetworktimeserver"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if r.returncode == 0:
                return {"source": "systemsetup", "output": r.stdout.strip()[:500]}
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def clock_check(
    servers=DEFAULT_NTP_SERVERS,
    timeout: float = 2.0,
    transport=_udp_transport,
    os_status: Callable[[], dict | None] = os_clock_status,
) -> dict:
    """Measure the clock state. Without a reply the state is "unknown", never "synchronised"."""
    record = {"type": "clock", "t_ns": time.time_ns()}
    errors = []
    for server in servers:
        try:
            reply = sntp_query(server, timeout, transport)
        except (OSError, ValueError) as e:
            errors.append(f"{server}: {e}")
            continue
        record["sntp"] = reply
        record["offset_s"] = reply["offset_s"]
        record["state"] = (
            "synchronised" if abs(reply["offset_s"]) <= SYNC_TOLERANCE_S else "not_synchronised"
        )
        break
    else:
        record["state"] = "unknown"
        record["sntp_errors"] = errors
    try:
        record["os_status"] = os_status()
    except Exception as e:  # the OS status is informative only
        record["os_status"] = {"error": str(e)}
    return record


class ClockMonitor:
    """Runs ``clock_check`` every ``period`` seconds in a background thread."""

    def __init__(
        self,
        on_record: Callable[[dict], None],
        period: float = CLOCK_CHECK_PERIOD_S,
        check: Callable[[], dict] = clock_check,
    ):
        self.on_record = on_record
        self.period = period
        self.check = check
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="clock-monitor", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.period):
            record = self.check()
            if self._stop.is_set():
                break
            self.on_record(record)

    def stop(self) -> None:
        self._stop.set()
