"""Command line: ``reapet doctor``, ``reapet record``, ``reapet recover``."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import __version__
from .acquisition import Block, BlockQueue, Recorder, RecorderConfig
from .bands import BANDS, LO_OFFSET_HZ, NARROW_PASSBAND_HZ, NARROW_RATE
from .context import ClockMonitor, ask_context, clock_check
from .device import (
    EVENT_OVERLOAD_ON,
    Device,
    DeviceError,
    ReadbackMismatch,
    TunerConfig,
    common_input,
    missing_capabilities,
)
from .dsp import CLIP_FRACTION, design_lowpass
from .fake_device import FakeDevice, FakeScenario, Tone
from .gain import DEFAULT_MARGIN_DB, propose_gain
from .session import Session, StreamSpec, recover

STOP_DB = 80.0
TUNER_BANDWIDTH_HZ = 1_536_000.0


# --- device opening ----------------------------------------------------------------


def _fake_from_args(args) -> FakeDevice:
    scenario = FakeScenario(tones=(Tone(LO_OFFSET_HZ + 1_500, -30.0), Tone(300_000, -25.0)))
    if getattr(args, "fake_scenario", None):
        raw = json.loads(Path(args.fake_scenario).read_text())
        raw["tones"] = tuple(Tone(**t) for t in raw.get("tones", []))
        for key in ("inputs", "clipping", "overload", "counter_gaps", "level_offset_db"):
            if key in raw:
                raw[key] = tuple(tuple(x) if isinstance(x, list) else x for x in raw[key])
        scenario = FakeScenario(**raw)
    return FakeDevice(scenario, speed=args.fake_speed)


@contextlib.contextmanager
def open_device(args, out):
    """Yield an opened device: the simulated one with --fake, otherwise the first RSPduo."""
    if args.fake:
        dev = _fake_from_args(args)
        try:
            yield dev
        finally:
            dev.close()
        return
    from .sdrplay import RspDuo, SdrplayApi

    api = SdrplayApi.load()
    api.open()
    try:
        api.check_version()
        dev = RspDuo.open_first(api)
        try:
            yield dev
        finally:
            dev.close()
    finally:
        api.close()


# --- doctor ------------------------------------------------------------------------


def reception_test(device: Device, seconds: float, *, fs: float) -> dict:
    """Stream both receivers for ``seconds`` and measure counters, gaps and A/B alignment."""
    q = BlockQueue(int(fs * 8))
    stats = [
        {
            "blocks": 0,
            "samples": 0,
            "first_counter": None,
            "gaps": 0,
            "gap_samples": 0,
            "resets": 0,
            "overload_events": 0,
            "next": None,
        }
        for _ in range(2)
    ]
    corr_len = 1 << 16
    keep = [[], []]
    device.start(q)
    t0 = time.monotonic()
    try:
        while True:
            if time.monotonic() - t0 >= seconds:
                break
            item = q.get(0.05)
            if item is None:
                continue
            if not isinstance(item, Block):
                if item.kind == EVENT_OVERLOAD_ON and item.channel is not None:
                    stats[item.channel]["overload_events"] += 1
                continue
            s = stats[item.channel]
            if s["first_counter"] is None:
                s["first_counter"] = item.counter
            if s["next"] is not None and item.counter != s["next"]:
                s["gaps"] += 1
                s["gap_samples"] += item.counter - s["next"]
            if item.flags:
                s["resets"] += 1
            s["next"] = item.counter + item.n
            s["blocks"] += 1
            s["samples"] += item.n
            if sum(len(b) for _, b in keep[item.channel]) < 4 * corr_len:
                keep[item.channel].append((item.counter, item.data.copy()))
            q.release(item)
        wall = time.monotonic() - t0
    finally:
        device.stop()
    result = {"seconds": round(wall, 2), "channels": []}
    for s in stats:
        s.pop("next")
        s["rate_sps"] = round(s["samples"] / wall, 1) if wall > 0 else None
        result["channels"].append(s)
    result["dropped_blocks"] = list(q.dropped_blocks)
    result["alignment"] = _alignment(keep, corr_len)
    return result


def _alignment(keep, n: int) -> dict | None:
    """Lag (samples) and coefficient of the A/B cross-correlation, with blocks placed by counter."""
    if not keep[0] or not keep[1]:
        return None
    start = max(keep[0][0][0], keep[1][0][0])
    xs = []
    for blocks in keep:
        end = max(c + len(d) for c, d in blocks)
        buf = np.zeros((end - start, 2), np.float32)
        for c, d in blocks:
            if c + len(d) > start:
                lo = max(c, start)
                buf[lo - start : c + len(d) - start] = d[lo - c :]
        xs.append(buf[:, 0] + 1j * buf[:, 1])
    m = min(len(xs[0]), len(xs[1]), n)
    if m < 1024:
        return None
    a, b = xs[0][:m] - xs[0][:m].mean(), xs[1][:m] - xs[1][:m].mean()
    spec = np.fft.fft(a, 2 * m) * np.conj(np.fft.fft(b, 2 * m))
    cc = np.fft.ifft(spec)
    lags = np.concatenate((np.arange(0, 65), np.arange(-64, 0)))
    window = np.concatenate((cc[:65], cc[-64:]))
    k = int(np.argmax(np.abs(window)))
    norm = np.sqrt(np.vdot(a, a).real * np.vdot(b, b).real)
    return {
        "lag_samples": int(lags[k]),
        "coefficient": round(float(abs(window[k]) / norm), 3) if norm else 0.0,
        "samples": m,
    }


def report_device(device: Device, out, *, seconds: float, band: str = "20m") -> int:
    info = device.info()
    caps = device.capabilities()
    out(f"Device: {info.name}, serial {info.serial}, driver {info.driver} {info.driver_version}")
    out(
        f"Receivers: {caps.receivers}; sample rates: "
        + ", ".join(f"{r / 1e6:g} MS/s" for r in caps.sample_rates)
        + f"; native format: {caps.native_format}"
    )
    out(
        f"Inputs per receiver: {[list(i) for i in caps.inputs]}; "
        f"overload events: {'yes' if caps.overload_events else 'no'}"
    )
    missing = missing_capabilities(caps)
    if missing:
        out("NOT suitable, missing: " + "; ".join(missing))
        return 1
    b = BANDS[band]
    inp = common_input(caps)
    steps = device.gain_steps(b.tuner_center_hz, inp)
    device.configure(
        TunerConfig(
            b.tuner_center_hz, caps.sample_rates[0], TUNER_BANDWIDTH_HZ, steps[len(steps) // 2], inp
        )
    )
    out(
        f"Reception test: {seconds:g} s on {band}, tuner at {b.tuner_center_hz / 1e6:.4f} MHz, "
        f"input {inp}"
    )
    r = reception_test(device, seconds, fs=caps.sample_rates[0])
    for name, s in zip("AB", r["channels"], strict=True):
        out(
            f"  tuner {name}: {s['blocks']} blocks, {s['samples']} samples, "
            f"{s['rate_sps'] / 1e6:.4f} MS/s, first counter {s['first_counter']}, "
            f"{s['gaps']} counter gaps ({s['gap_samples']} samples), {s['resets']} resets, "
            f"{s['overload_events']} overload events"
        )
    out(f"  dropped blocks (queue full): {r['dropped_blocks']}")
    out(f"  counter info: {device.counter_info()}")
    al = r["alignment"]
    if al:
        out(
            f"  A/B cross-correlation: lag {al['lag_samples']} samples, coefficient "
            f"{al['coefficient']} over {al['samples']} samples "
            "(with one antenna on both inputs through a splitter, expect lag 0)"
        )
    problems = []
    if any(s["samples"] == 0 for s in r["channels"]):
        problems.append("a tuner delivered no samples")
    if any(s["gaps"] for s in r["channels"]) or any(r["dropped_blocks"]):
        problems.append("samples were lost during the test")
    if problems:
        out("NOT suitable: " + "; ".join(problems))
        return 1
    out("Suitable for recording.")
    return 0


def cmd_doctor(args, out=print) -> int:
    out(f"reAPET {__version__}")
    if args.fake:
        dev = _fake_from_args(args)
        try:
            return report_device(dev, out, seconds=args.seconds, band=args.band)
        finally:
            dev.close()
    from .sdrplay import SUPPORTED_API_VERSIONS, ApiMissing, RspDuo, SdrplayApi, describe

    try:
        api = SdrplayApi.load()
    except ApiMissing as e:
        out(str(e))
        return 1
    out(f"SDRplay API library: {api.path}")
    try:
        api.open()
    except DeviceError as e:
        out(f"{e}. Check that the SDRplay API service is installed and running.")
        return 1
    try:
        version = api.version()
        out(f"SDRplay API version: {version:.2f}")
        if version not in SUPPORTED_API_VERSIONS:
            out(
                "This API version is not supported (supported: "
                + ", ".join(f"{v:.2f}" for v in SUPPORTED_API_VERSIONS)
                + "). Not continuing."
            )
            return 1
        devices = api.devices()
        if not devices:
            out("No device found.")
            return 1
        for d in devices:
            desc = describe(d)
            modes = (
                f", RSPduo modes: {', '.join(desc['rspduo_modes'])}"
                if desc["rspduo_modes"] is not None
                else ""
            )
            out(f"Found {desc['model']} serial {desc['serial']}{modes}")
        try:
            duo = RspDuo.open_first(api)
        except DeviceError as e:
            out(f"{e}. reAPET needs an RSPduo in dual-tuner mode.")
            return 1
        try:
            return report_device(duo, out, seconds=args.seconds, band=args.band)
        finally:
            duo.close()
    except DeviceError as e:
        out(str(e))
        return 1
    finally:
        api.close()


# --- record ------------------------------------------------------------------------


def _status_line(st) -> str:
    def ch(c):
        sat = f"sat {c.saturation_intervals}{'+' if c.saturation_open else ''}"
        ovl = f"ovl {c.overload_intervals}{'+' if c.overload_open else ''}"
        return f"{sat} {ovl} peak {c.last_peak_dbfs:6.1f} dBFS"

    secs = int(st.seconds)
    disk = f"{st.disk_free_bytes / 1e9:.1f} GB free" if st.disk_free_bytes is not None else "disk ?"
    state = "REC" if st.recording else f"CLOSED ({st.close_reason})"
    return (
        f"{state} {secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d} | "
        f"A: {ch(st.channels[0])} | B: {ch(st.channels[1])} | gaps {st.gaps} "
        f"dropped {st.dropped_blocks} | {disk}"
    )


def cmd_record(args, out=print, input_fn=input) -> int:
    band = BANDS[args.band]
    with open_device(args, out) as device:
        caps = device.capabilities()
        missing = missing_capabilities(caps)
        if missing:
            out("This device cannot record a comparison. Missing: " + "; ".join(missing))
            return 2
        given = {
            k: v
            for k, v in (
                ("antenna_a", args.antenna_a),
                ("antenna_b", args.antenna_b),
                ("locator", args.locator),
            )
            if v is not None
        }
        ctx = ask_context(input_fn=input_fn, print_fn=out, given=given)
        for item in ctx["missing"]:
            out(f"Note: {item} not given; the session records it as missing.")
        clock_start = (
            clock_check()
            if not args.no_sntp
            else {
                "type": "clock",
                "t_ns": time.time_ns(),
                "state": "unknown",
                "skipped": "--no-sntp",
            }
        )
        out(
            f"Clock: {clock_start['state']}"
            + (f", offset {clock_start['offset_s']:+.3f} s" if "offset_s" in clock_start else "")
        )

        fs = caps.sample_rates[0]
        factor = int(round(fs / NARROW_RATE))
        inp = common_input(caps)
        steps = device.gain_steps(band.tuner_center_hz, inp)
        device.configure(TunerConfig(band.tuner_center_hz, fs, TUNER_BANDWIDTH_HZ, steps[0], inp))
        q = BlockQueue(int(fs * 4))
        device.start(q)
        try:
            out("Headroom check...")
            proposal = propose_gain(
                device, q, steps, fs=fs, full_scale=caps.full_scale, margin_db=args.margin_db
            )
            s = proposal.step
            out(
                f"Gain: LNA state {s.lna_state}, IF reduction {s.if_gr_db} dB "
                f"(total reduction {s.total_gr_db:g} dB)"
                + (
                    ""
                    if proposal.margin_met
                    else f"; WARNING: no gain leaves {args.margin_db:g} dB of margin"
                )
            )
            try:
                readbacks = device.lock()
            except ReadbackMismatch as e:
                out(f"Not recording: {e}")
                return 3
            q.drain()

            taps = design_lowpass(fs, factor, NARROW_PASSBAND_HZ, STOP_DB)
            shift = band.slice_center_hz - band.tuner_center_hz
            streams = [
                StreamSpec(f"rx-{c}", c, "narrow", "cf32_le", fs / factor, band.slice_center_hz)
                for c in "AB"
            ]
            if args.store_wide:
                streams += [
                    StreamSpec(f"rx-{c}-wide", c, "wide", "ci16_le", fs, band.tuner_center_hz)
                    for c in "AB"
                ]
            context = {
                **ctx,
                "device": {
                    **dataclasses.asdict(device.info()),
                    "capabilities": dataclasses.asdict(caps),
                    "counter": device.counter_info(),
                },
                "readback": [rb.as_dict() for rb in readbacks],
                "gain": proposal.as_dict(),
                "band": band.as_dict(),
                "input": inp,
                "clock_start": clock_start,
                "saturation_detection": {
                    "iq": {
                        "available": True,
                        "threshold_fraction": CLIP_FRACTION,
                        "hold_s": 1.0,
                        "measured_on": "wide band, before decimation",
                    },
                    "device_overload": {"available": caps.overload_events},
                },
                "store_wide": args.store_wide,
            }
            decimation = {
                "factor": factor,
                "taps": len(taps),
                "passband_hz": NARROW_PASSBAND_HZ,
                "stop_db": STOP_DB,
                "shift_hz": shift,
                "delay_wide_samples": (len(taps) - 1) / 2,
                "transient_outputs_per_segment": len(taps) // factor,
                "full_scale_narrow": 1.0,
                "full_scale_wide": caps.full_scale,
            }
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            path = Path(args.out) / f"{stamp}-{band.name}"
            session = Session(path, {"context": context, "decimation": decimation}, streams)
            out(f"Recording to {path}  (Ctrl-C to stop)")

            def final_clock():
                if not args.no_sntp:
                    session.journal(clock_check())

            rec = Recorder(
                session,
                q,
                RecorderConfig(
                    fs=fs,
                    full_scale=caps.full_scale,
                    decimation_factor=factor,
                    shift_hz=shift,
                    taps=taps,
                    store_wide=args.store_wide,
                ),
                before_close=final_clock,
            )
            monitor = None
            if not args.no_sntp:
                monitor = ClockMonitor(session.journal)
                monitor.start()
            stop = threading.Event()
            latest = {}
            writer = threading.Thread(
                target=rec.run,
                args=(stop,),
                kwargs={"on_status": lambda st: latest.update(st=st)},
                name="writer",
            )
            writer.start()
            t0 = time.monotonic()
            tty = sys.stdout.isatty()
            try:
                while writer.is_alive():
                    writer.join(1.0)
                    if args.duration and time.monotonic() - t0 >= args.duration:
                        stop.set()
                    if "st" in latest and tty:
                        print("\r" + _status_line(latest["st"]), end="", flush=True)
            except KeyboardInterrupt:
                stop.set()
                writer.join()
            if tty:
                print()
            if monitor:
                monitor.stop()
            st = rec.status
            out(_status_line(st))
            out(f"Session closed ({st.close_reason}): {path}")
            return 0 if st.close_reason == "stop" else 1
        finally:
            device.stop()


def cmd_recover(args, out=print) -> int:
    paths = recover(Path(args.session))
    out(f"Rebuilt {paths['collection']}")
    return 0


# --- entry point -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reapet", description="reAPET dual-receiver IQ recorder")
    p.add_argument("--version", action="version", version=f"reAPET {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def device_args(sp):
        sp.add_argument("--fake", action="store_true", help="use the simulated device")
        sp.add_argument("--fake-scenario", help="JSON file with simulated device settings")
        sp.add_argument(
            "--fake-speed",
            type=float,
            default=1.0,
            help="simulated device speed (inf = as fast as possible)",
        )
        sp.add_argument(
            "--band", choices=sorted(BANDS, key=lambda b: BANDS[b].ft8_dial_hz), default="20m"
        )

    d = sub.add_parser("doctor", help="check the installation and the device")
    device_args(d)
    d.add_argument("--seconds", type=float, default=5.0, help="length of the reception test")

    r = sub.add_parser("record", help="record a session")
    device_args(r)
    r.add_argument("--out", default="sessions", help="folder for the sessions")
    r.add_argument("--store-wide", action="store_true", help="also store the wide band (large)")
    r.add_argument("--duration", type=float, help="stop after this many seconds")
    r.add_argument("--antenna-a", help="antenna on receiver A (asked if omitted)")
    r.add_argument("--antenna-b", help="antenna on receiver B (asked if omitted)")
    r.add_argument("--locator", help="Maidenhead locator (asked if omitted)")
    r.add_argument(
        "--margin-db",
        type=float,
        default=DEFAULT_MARGIN_DB,
        help="peak margin below full scale for the gain proposal",
    )
    r.add_argument("--no-sntp", action="store_true", help="do not query time servers")

    rc = sub.add_parser("recover", help="rebuild an interrupted session")
    rc.add_argument("session", help="session folder")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "record":
            return cmd_record(args)
        return cmd_recover(args)
    except DeviceError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
