"""SDRplay API v3 backend for the RSPduo in dual-tuner mode (ctypes, KTD14).

Structures follow the "SDRplay API Specification" v3.15 (section 2). Every tuner
parameter is set on the structure of its own tuner (``rxChannelA``,
``rxChannelB``) and read back from there; overload events are acknowledged and
forwarded per tuner; ``firstSampleNum`` is unwrapped to a 64-bit counter.

Dual-tuner mode is used at 6 MHz ADC rate with a 1.620 MHz IF and 1.536 MHz
bandwidth: the API down-converts and delivers 2 MS/s per tuner.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import threading
import time
from pathlib import Path

import numpy as np

from .device import (
    EVENT_FAILURE,
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

SUPPORTED_API_VERSIONS = (3.15,)
INSTALL_HINT = (
    "Install the SDRplay API 3.15 with the official installer from "
    "https://www.sdrplay.com/api/ (Windows, macOS, Linux). It installs the library "
    "and the API service; reAPET needs nothing else. To use a library in a "
    "non-standard place, set REAPET_SDRPLAY_API to its full path."
)

# --- constants (spec 2.1.2 and enums) --------------------------------------------

MAX_DEVICES = 16
RSPDUO_ID = 3
HW_NAMES = {1: "RSP1", 255: "RSP1A", 2: "RSP2", 3: "RSPduo", 4: "RSPdx", 6: "RSP1B", 7: "RSPdxR2"}

SUCCESS = 0
TUNER_A, TUNER_B, TUNER_BOTH = 1, 2, 3
DUO_SINGLE, DUO_DUAL, DUO_MASTER, DUO_SLAVE = 1, 2, 4, 8
BW_1_536 = 1536
IF_1_620 = 1620
AGC_DISABLE = 0
NORMAL_MIN_GR = 20
AMPORT_1, AMPORT_2 = 1, 0  # AMPORT_1 is the Hi-Z input of tuner 1
EV_GAIN, EV_OVERLOAD, EV_REMOVED, EV_DUO_MODE, EV_FAILURE = 0, 1, 2, 3, 4
OVERLOAD_DETECTED = 0

UPDATE_TUNER_GR = 0x00008000
UPDATE_CTRL_OVERLOAD_ACK = 0x04000000
UPDATE_EXT1_NONE = 0

DUAL_ADC_RATE = 6_000_000.0
DUAL_OUTPUT_RATE = 2_000_000.0
FULL_SCALE = 32767
MIN_IF_GR, MAX_IF_GR = 20, 59

# RSPduo LNA gain reduction (dB) per LNAstate, 0-60 MHz (spec section 5).
LNA_GR_50OHM = (0, 6, 12, 18, 37, 42, 61)
LNA_GR_HIZ = (0, 6, 12, 18, 37)

HANDLE = ctypes.c_void_p
c_enum = ctypes.c_int


# --- structures (spec section 2) -------------------------------------------------


class DeviceT(ctypes.Structure):
    _fields_ = [
        ("SerNo", ctypes.c_char * 64),
        ("hwVer", ctypes.c_ubyte),
        ("tuner", c_enum),
        ("rspDuoMode", c_enum),
        ("valid", ctypes.c_ubyte),
        ("rspDuoSampleFreq", ctypes.c_double),
        ("dev", HANDLE),
    ]


class ErrorInfoT(ctypes.Structure):
    _fields_ = [
        ("file", ctypes.c_char * 256),
        ("function", ctypes.c_char * 256),
        ("line", ctypes.c_int),
        ("message", ctypes.c_char * 1024),
    ]


class FsFreqT(ctypes.Structure):
    _fields_ = [
        ("fsHz", ctypes.c_double),
        ("syncUpdate", ctypes.c_ubyte),
        ("reCal", ctypes.c_ubyte),
    ]


class SyncUpdateT(ctypes.Structure):
    _fields_ = [("sampleNum", ctypes.c_uint), ("period", ctypes.c_uint)]


class ResetFlagsT(ctypes.Structure):
    _fields_ = [
        ("resetGainUpdate", ctypes.c_ubyte),
        ("resetRfUpdate", ctypes.c_ubyte),
        ("resetFsUpdate", ctypes.c_ubyte),
    ]


class Rsp1aParamsT(ctypes.Structure):
    _fields_ = [("rfNotchEnable", ctypes.c_ubyte), ("rfDabNotchEnable", ctypes.c_ubyte)]


class Rsp2ParamsT(ctypes.Structure):
    _fields_ = [("extRefOutputEn", ctypes.c_ubyte)]


class RspDuoParamsT(ctypes.Structure):
    _fields_ = [("extRefOutputEn", ctypes.c_int)]


class RspDxParamsT(ctypes.Structure):
    _fields_ = [
        ("hdrEnable", ctypes.c_ubyte),
        ("biasTEnable", ctypes.c_ubyte),
        ("antennaSel", c_enum),
        ("rfNotchEnable", ctypes.c_ubyte),
        ("rfDabNotchEnable", ctypes.c_ubyte),
    ]


class DevParamsT(ctypes.Structure):
    _fields_ = [
        ("ppm", ctypes.c_double),
        ("fsFreq", FsFreqT),
        ("syncUpdate", SyncUpdateT),
        ("resetFlags", ResetFlagsT),
        ("mode", c_enum),
        ("samplesPerPkt", ctypes.c_uint),
        ("rsp1aParams", Rsp1aParamsT),
        ("rsp2Params", Rsp2ParamsT),
        ("rspDuoParams", RspDuoParamsT),
        ("rspDxParams", RspDxParamsT),
    ]


class GainValuesT(ctypes.Structure):
    _fields_ = [("curr", ctypes.c_float), ("max", ctypes.c_float), ("min", ctypes.c_float)]


class GainT(ctypes.Structure):
    _fields_ = [
        ("gRdB", ctypes.c_int),
        ("LNAstate", ctypes.c_ubyte),
        ("syncUpdate", ctypes.c_ubyte),
        ("minGr", c_enum),
        ("gainVals", GainValuesT),
    ]


class RfFreqT(ctypes.Structure):
    _fields_ = [("rfHz", ctypes.c_double), ("syncUpdate", ctypes.c_ubyte)]


class DcOffsetTunerT(ctypes.Structure):
    _fields_ = [
        ("dcCal", ctypes.c_ubyte),
        ("speedUp", ctypes.c_ubyte),
        ("trackTime", ctypes.c_int),
        ("refreshRateTime", ctypes.c_int),
    ]


class TunerParamsT(ctypes.Structure):
    _fields_ = [
        ("bwType", c_enum),
        ("ifType", c_enum),
        ("loMode", c_enum),
        ("gain", GainT),
        ("rfFreq", RfFreqT),
        ("dcOffsetTuner", DcOffsetTunerT),
    ]


class DcOffsetT(ctypes.Structure):
    _fields_ = [("DCenable", ctypes.c_ubyte), ("IQenable", ctypes.c_ubyte)]


class DecimationT(ctypes.Structure):
    _fields_ = [
        ("enable", ctypes.c_ubyte),
        ("decimationFactor", ctypes.c_ubyte),
        ("wideBandSignal", ctypes.c_ubyte),
    ]


class AgcT(ctypes.Structure):
    _fields_ = [
        ("enable", c_enum),
        ("setPoint_dBfs", ctypes.c_int),
        ("attack_ms", ctypes.c_ushort),
        ("decay_ms", ctypes.c_ushort),
        ("decay_delay_ms", ctypes.c_ushort),
        ("decay_threshold_dB", ctypes.c_ushort),
        ("syncUpdate", ctypes.c_int),
    ]


class ControlParamsT(ctypes.Structure):
    _fields_ = [
        ("dcOffset", DcOffsetT),
        ("decimation", DecimationT),
        ("agc", AgcT),
        ("adsbMode", c_enum),
    ]


class Rsp1aTunerParamsT(ctypes.Structure):
    _fields_ = [("biasTEnable", ctypes.c_ubyte)]


class Rsp2TunerParamsT(ctypes.Structure):
    _fields_ = [
        ("biasTEnable", ctypes.c_ubyte),
        ("amPortSel", c_enum),
        ("antennaSel", c_enum),
        ("rfNotchEnable", ctypes.c_ubyte),
    ]


class RspDuoResetSlaveFlagsT(ctypes.Structure):
    _fields_ = [("resetGainUpdate", ctypes.c_ubyte), ("resetRfUpdate", ctypes.c_ubyte)]


class RspDuoTunerParamsT(ctypes.Structure):
    _fields_ = [
        ("biasTEnable", ctypes.c_ubyte),
        ("tuner1AmPortSel", c_enum),
        ("tuner1AmNotchEnable", ctypes.c_ubyte),
        ("rfNotchEnable", ctypes.c_ubyte),
        ("rfDabNotchEnable", ctypes.c_ubyte),
        ("resetSlaveFlags", RspDuoResetSlaveFlagsT),
    ]


class RspDxTunerParamsT(ctypes.Structure):
    _fields_ = [("hdrBw", c_enum)]


class RxChannelParamsT(ctypes.Structure):
    _fields_ = [
        ("tunerParams", TunerParamsT),
        ("ctrlParams", ControlParamsT),
        ("rsp1aTunerParams", Rsp1aTunerParamsT),
        ("rsp2TunerParams", Rsp2TunerParamsT),
        ("rspDuoTunerParams", RspDuoTunerParamsT),
        ("rspDxTunerParams", RspDxTunerParamsT),
    ]


class DeviceParamsT(ctypes.Structure):
    _fields_ = [
        ("devParams", ctypes.POINTER(DevParamsT)),
        ("rxChannelA", ctypes.POINTER(RxChannelParamsT)),
        ("rxChannelB", ctypes.POINTER(RxChannelParamsT)),
    ]


class StreamCbParamsT(ctypes.Structure):
    _fields_ = [
        ("firstSampleNum", ctypes.c_uint),
        ("grChanged", ctypes.c_int),
        ("rfChanged", ctypes.c_int),
        ("fsChanged", ctypes.c_int),
        ("numSamples", ctypes.c_uint),
    ]


class GainCbParamT(ctypes.Structure):
    _fields_ = [("gRdB", ctypes.c_uint), ("lnaGRdB", ctypes.c_uint), ("currGain", ctypes.c_double)]


class PowerOverloadCbParamT(ctypes.Structure):
    _fields_ = [("powerOverloadChangeType", c_enum)]


class RspDuoModeCbParamT(ctypes.Structure):
    _fields_ = [("modeChangeType", c_enum)]


class EventParamsT(ctypes.Union):
    _fields_ = [
        ("gainParams", GainCbParamT),
        ("powerOverloadParams", PowerOverloadCbParamT),
        ("rspDuoModeParams", RspDuoModeCbParamT),
    ]


StreamCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(ctypes.c_short),
    ctypes.POINTER(ctypes.c_short),
    ctypes.POINTER(StreamCbParamsT),
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
)
EventCallback = ctypes.CFUNCTYPE(
    None, c_enum, c_enum, ctypes.POINTER(EventParamsT), ctypes.c_void_p
)


class CallbackFnsT(ctypes.Structure):
    _fields_ = [
        ("StreamACbFn", StreamCallback),
        ("StreamBCbFn", StreamCallback),
        ("EventCbFn", EventCallback),
    ]


# --- library ---------------------------------------------------------------------


class ApiMissing(DeviceError):
    pass


class ApiVersionUnsupported(DeviceError):
    pass


def library_candidates() -> list[str]:
    env = os.environ.get("REAPET_SDRPLAY_API")
    if env:
        return [env]
    out = []
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            for key in (
                r"SOFTWARE\SDRplay\Service\API",
                r"SOFTWARE\WOW6432Node\SDRplay\Service\API",
            ):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                        out.append(
                            str(
                                Path(winreg.QueryValueEx(k, "Install_Dir")[0])
                                / "x64"
                                / "sdrplay_api.dll"
                            )
                        )
                except OSError:
                    pass
        except ImportError:
            pass
        out.append(r"C:\Program Files\SDRplay\API\x64\sdrplay_api.dll")
    else:
        out += [
            "/usr/local/lib/libsdrplay_api.so.3",
            "/usr/local/lib/libsdrplay_api.so",
            "/usr/local/lib/libsdrplay_api.dylib",
            "/opt/homebrew/lib/libsdrplay_api.so.3",
        ]
    found = ctypes.util.find_library("sdrplay_api")
    if found:
        out.append(found)
    return out


def load_library(candidates: list[str] | None = None):
    tried = []
    for path in candidates if candidates is not None else library_candidates():
        try:
            return ctypes.CDLL(path), path
        except OSError as e:
            tried.append(f"{path}: {e}")
    raise ApiMissing(
        "SDRplay API library not found. "
        + INSTALL_HINT
        + ("\nTried:\n  " + "\n  ".join(tried) if tried else "")
    )


class SdrplayApi:
    """Thin wrapper over the library functions; raises DeviceError on failures."""

    def __init__(self, lib, path: str = ""):
        self.lib = lib
        self.path = path
        sigs = {
            "sdrplay_api_Open": [],
            "sdrplay_api_Close": [],
            "sdrplay_api_ApiVersion": [ctypes.POINTER(ctypes.c_float)],
            "sdrplay_api_LockDeviceApi": [],
            "sdrplay_api_UnlockDeviceApi": [],
            "sdrplay_api_GetDevices": [
                ctypes.POINTER(DeviceT),
                ctypes.POINTER(ctypes.c_uint),
                ctypes.c_uint,
            ],
            "sdrplay_api_SelectDevice": [ctypes.POINTER(DeviceT)],
            "sdrplay_api_ReleaseDevice": [ctypes.POINTER(DeviceT)],
            "sdrplay_api_GetDeviceParams": [HANDLE, ctypes.POINTER(ctypes.POINTER(DeviceParamsT))],
            "sdrplay_api_Init": [HANDLE, ctypes.POINTER(CallbackFnsT), ctypes.c_void_p],
            "sdrplay_api_Uninit": [HANDLE],
            "sdrplay_api_Update": [HANDLE, c_enum, ctypes.c_uint, ctypes.c_uint],
        }
        for name, args in sigs.items():
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = c_enum
        lib.sdrplay_api_GetErrorString.argtypes = [c_enum]
        lib.sdrplay_api_GetErrorString.restype = ctypes.c_char_p
        lib.sdrplay_api_GetLastError.argtypes = [ctypes.POINTER(DeviceT)]
        lib.sdrplay_api_GetLastError.restype = ctypes.POINTER(ErrorInfoT)
        self.is_open = False

    @classmethod
    def load(cls, candidates: list[str] | None = None) -> SdrplayApi:
        lib, path = load_library(candidates)
        return cls(lib, path)

    def _check(self, err: int, what: str) -> None:
        if err != SUCCESS:
            msg = self.lib.sdrplay_api_GetErrorString(err)
            text = msg.decode(errors="replace") if msg else f"error {err}"
            raise DeviceError(f"{what} failed: {text}")

    def open(self) -> None:
        self._check(self.lib.sdrplay_api_Open(), "sdrplay_api_Open (is the API service running?)")
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            self.lib.sdrplay_api_Close()
            self.is_open = False

    def version(self) -> float:
        v = ctypes.c_float(0)
        self._check(self.lib.sdrplay_api_ApiVersion(ctypes.byref(v)), "sdrplay_api_ApiVersion")
        return round(v.value, 2)

    def check_version(self) -> float:
        v = self.version()
        if v not in SUPPORTED_API_VERSIONS:
            raise ApiVersionUnsupported(
                f"SDRplay API {v:.2f} is not supported; reAPET supports "
                + ", ".join(f"{x:.2f}" for x in SUPPORTED_API_VERSIONS)
                + ". The structures read through ctypes could differ. "
                + INSTALL_HINT
            )
        return v

    def devices(self) -> list[DeviceT]:
        arr = (DeviceT * MAX_DEVICES)()
        n = ctypes.c_uint(0)
        self.lib.sdrplay_api_LockDeviceApi()
        try:
            self._check(
                self.lib.sdrplay_api_GetDevices(arr, ctypes.byref(n), MAX_DEVICES),
                "sdrplay_api_GetDevices",
            )
        finally:
            self.lib.sdrplay_api_UnlockDeviceApi()
        return [arr[i] for i in range(n.value)]


def describe(dev: DeviceT) -> dict:
    modes = [
        name
        for bit, name in (
            (DUO_SINGLE, "single"),
            (DUO_DUAL, "dual"),
            (DUO_MASTER, "master"),
            (DUO_SLAVE, "slave"),
        )
        if dev.rspDuoMode & bit
    ]
    return {
        "model": HW_NAMES.get(dev.hwVer, f"hw {dev.hwVer}"),
        "serial": dev.SerNo.decode(errors="replace"),
        "tuners": dev.tuner,
        "rspduo_modes": modes if dev.hwVer == RSPDUO_ID else None,
    }


def gain_ladder(lna_table: tuple[int, ...], step_db: int = 3) -> list[GainStep]:
    """Gain steps from the highest gain to the lowest, about ``step_db`` apart.

    For each total gain reduction the LNA state that keeps the IF gain
    reduction closest to the middle of its range is used.
    """
    combos = {}
    for lna, lna_gr in enumerate(lna_table):
        for if_gr in range(MIN_IF_GR, MAX_IF_GR + 1):
            total = lna_gr + if_gr
            best = combos.get(total)
            if best is None or abs(if_gr - 40) < abs(best[1] - 40):
                combos[total] = (lna, if_gr)
    steps = []
    last = None
    for total in sorted(combos):
        if last is None or total - last >= step_db:
            lna, if_gr = combos[total]
            steps.append(GainStep(lna_state=lna, if_gr_db=if_gr, total_gr_db=float(total)))
            last = total
    lowest = max(combos)
    if last != lowest:  # always offer the lowest gain, the fallback of the headroom check
        lna, if_gr = combos[lowest]
        steps.append(GainStep(lna_state=lna, if_gr_db=if_gr, total_gr_db=float(lowest)))
    return steps


class _Unwrapper:
    """Turns the 32-bit ``firstSampleNum`` into a 64-bit counter in output samples.

    The counter step (counter units per delivered sample) is learnt from the
    first two blocks after a reset. A backwards jump that is not a wrap is a reset.
    """

    def __init__(self):
        self.last_raw = None
        self.total = 0
        self.prev_n = 0
        self.step = None

    def push(self, raw: int, n: int) -> tuple[int, bool]:
        reset = False
        if self.last_raw is None:
            self.total = raw
        else:
            delta = (raw - self.last_raw) & 0xFFFFFFFF
            if delta >= 1 << 31:
                reset = True
                self.total = raw
                self.step = None
            else:
                if (
                    self.step is None
                    and self.prev_n
                    and delta % self.prev_n == 0
                    and 1 <= delta // self.prev_n <= 8
                ):
                    self.step = delta // self.prev_n
                self.total += delta
        self.last_raw = raw
        self.prev_n = n
        return self.total // (self.step or 1), reset


class RspDuo(Device):
    """An RSPduo opened in dual-tuner mode."""

    def __init__(self, api: SdrplayApi, dev: DeviceT):
        super().__init__()
        self.api = api
        self.dev = dev
        self.params: ctypes.POINTER(DeviceParamsT) | None = None
        self._sink: Sink | None = None
        self._cbs = None
        self._running = False
        self._gain_events = [threading.Event(), threading.Event()]
        self._unwrap = [_Unwrapper(), _Unwrapper()]
        self.api_version = api.version()
        self.blocks_seen = [0, 0]

    @classmethod
    def open_first(cls, api: SdrplayApi) -> RspDuo:
        for dev in api.devices():
            if dev.hwVer == RSPDUO_ID:
                duo = cls(api, dev)
                duo.select()
                return duo
        raise DeviceError("no RSPduo found")

    def select(self) -> None:
        if not self.dev.rspDuoMode & DUO_DUAL:
            raise DeviceError(
                "this RSPduo does not offer dual-tuner mode now (is it in use by another program?)"
            )
        lib = self.api.lib
        self.dev.tuner = TUNER_BOTH
        self.dev.rspDuoMode = DUO_DUAL
        self.dev.rspDuoSampleFreq = DUAL_ADC_RATE
        lib.sdrplay_api_LockDeviceApi()
        try:
            self.api._check(
                lib.sdrplay_api_SelectDevice(ctypes.byref(self.dev)),
                "sdrplay_api_SelectDevice (dual tuner)",
            )
        finally:
            lib.sdrplay_api_UnlockDeviceApi()
        p = ctypes.POINTER(DeviceParamsT)()
        self.api._check(
            lib.sdrplay_api_GetDeviceParams(self.dev.dev, ctypes.byref(p)),
            "sdrplay_api_GetDeviceParams",
        )
        if not p or not p.contents.rxChannelA or not p.contents.rxChannelB:
            raise DeviceError("the API returned no parameters for both tuners")
        self.params = p

    def _channels(self):
        p = self.params.contents
        return (p.rxChannelA.contents, p.rxChannelB.contents)

    # --- description -------------------------------------------------------------

    def info(self) -> DeviceInfo:
        return DeviceInfo(
            name="SDRplay RSPduo (dual tuner)",
            serial=self.dev.SerNo.decode(errors="replace"),
            driver="SDRplay API",
            driver_version=f"{self.api_version:.2f}",
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(
            receivers=2,
            same_clock=True,
            sample_counter=True,
            agc_can_disable=True,
            manual_gain=True,
            overload_events=True,
            sample_rates=(DUAL_OUTPUT_RATE,),
            native_format="ci16_le",
            full_scale=FULL_SCALE,
            inputs=(("50ohm", "hiz"), ("50ohm",)),
        )

    def gain_steps(self, center_hz: float, input_name: str) -> list[GainStep]:
        if center_hz > 60e6:
            raise DeviceError("reAPET supports HF only (below 60 MHz)")
        return gain_ladder(LNA_GR_HIZ if input_name == "hiz" else LNA_GR_50OHM)

    # --- settings ----------------------------------------------------------------

    def configure(self, config: TunerConfig) -> None:
        self._check_unlocked()
        if self._running:
            raise DeviceError("configure before starting the stream")
        if config.sample_rate != DUAL_OUTPUT_RATE:
            raise DeviceError("dual-tuner mode delivers 2 MS/s per tuner")
        for ch in self._channels():
            t = ch.tunerParams
            t.rfFreq.rfHz = config.center_hz
            t.bwType = BW_1_536
            t.ifType = IF_1_620
            t.gain.minGr = NORMAL_MIN_GR
            t.gain.gRdB = config.gain.if_gr_db
            t.gain.LNAstate = config.gain.lna_state
            c = ch.ctrlParams
            c.agc.enable = AGC_DISABLE
            c.decimation.enable = 0
            c.decimation.decimationFactor = 1
            d = ch.rspDuoTunerParams
            d.biasTEnable = 0
            d.tuner1AmPortSel = AMPORT_1 if config.input == "hiz" else AMPORT_2
            d.tuner1AmNotchEnable = 0
            d.rfNotchEnable = 0
            d.rfDabNotchEnable = 0

    def set_gain(self, step: GainStep) -> None:
        self._check_unlocked()
        for ch in self._channels():
            ch.tunerParams.gain.gRdB = step.if_gr_db
            ch.tunerParams.gain.LNAstate = step.lna_state
        if self._running:
            for k, tuner in enumerate((TUNER_A, TUNER_B)):
                self._gain_events[k].clear()
                self.api._check(
                    self.api.lib.sdrplay_api_Update(
                        self.dev.dev, tuner, UPDATE_TUNER_GR, UPDATE_EXT1_NONE
                    ),
                    "sdrplay_api_Update (gain)",
                )
            for ev in self._gain_events:
                ev.wait(1.0)

    def readback(self) -> list[TunerReadback]:
        out = []
        for name, ch in zip(("A", "B"), self._channels(), strict=True):
            t, c, d = ch.tunerParams, ch.ctrlParams, ch.rspDuoTunerParams
            hiz = name == "A" and d.tuner1AmPortSel == AMPORT_1
            out.append(
                TunerReadback(
                    channel=name,
                    center_hz=t.rfFreq.rfHz,
                    sample_rate=self.dev.rspDuoSampleFreq / 3 if t.ifType == IF_1_620 else 0.0,
                    bandwidth_hz=t.bwType * 1000.0,
                    lna_state=t.gain.LNAstate,
                    if_gr_db=t.gain.gRdB,
                    agc_enabled=c.agc.enable != AGC_DISABLE,
                    input="hiz" if hiz else "50ohm",
                    extra={
                        "if_khz": t.ifType,
                        "lo_mode": t.loMode,
                        "min_gr": t.gain.minGr,
                        "dc_correction": c.dcOffset.DCenable,
                        "iq_correction": c.dcOffset.IQenable,
                        "decimation": c.decimation.enable,
                        "bias_t": d.biasTEnable,
                        "rf_notch": d.rfNotchEnable,
                        "dab_notch": d.rfDabNotchEnable,
                        "am_notch": d.tuner1AmNotchEnable,
                    },
                    reported={
                        "gain_curr_db": round(t.gain.gainVals.curr, 2),
                        "gain_max_db": round(t.gain.gainVals.max, 2),
                        "gain_min_db": round(t.gain.gainVals.min, 2),
                        "adc_rate": self.dev.rspDuoSampleFreq,
                    },
                )
            )
        return out

    # --- streaming ---------------------------------------------------------------

    def _make_stream_cb(self, k: int):
        unwrap = self._unwrap[k]

        def cb(xi, xq, params, num_samples, reset, ctx):
            try:
                t_ns = time.time_ns()
                p = params.contents
                n = int(num_samples)
                counter, jumped_back = unwrap.push(p.firstSampleNum, n)
                flags = 1 if (reset or jumped_back) else 0
                i = np.ctypeslib.as_array(xi, shape=(n,))
                q = np.ctypeslib.as_array(xq, shape=(n,))
                self.blocks_seen[k] += 1
                self._sink.push_block(k, counter, i, q, t_ns, flags)
            except Exception:  # never let an exception reach the API thread
                pass

        return StreamCallback(cb)

    def _event_cb(self, event_id, tuner, params, ctx):
        try:
            t_ns = time.time_ns()
            k = 0 if tuner == TUNER_A else 1
            if event_id == EV_OVERLOAD:
                detected = (
                    params.contents.powerOverloadParams.powerOverloadChangeType == OVERLOAD_DETECTED
                )
                self.api.lib.sdrplay_api_Update(
                    self.dev.dev, tuner, UPDATE_CTRL_OVERLOAD_ACK, UPDATE_EXT1_NONE
                )
                self._sink.push_event(
                    k, EVENT_OVERLOAD_ON if detected else EVENT_OVERLOAD_OFF, t_ns
                )
            elif event_id == EV_GAIN:
                self._gain_events[k].set()
            elif event_id == EV_REMOVED:
                self._sink.push_event(None, EVENT_REMOVED, t_ns)
            elif event_id == EV_FAILURE:
                self._sink.push_event(None, EVENT_FAILURE, t_ns)
        except Exception:
            pass

    def start(self, sink: Sink) -> None:
        self._sink = sink
        self._unwrap[0].__init__()
        self._unwrap[1].__init__()
        cbs = CallbackFnsT(
            self._make_stream_cb(0), self._make_stream_cb(1), EventCallback(self._event_cb)
        )
        self._cbs = cbs  # keep the callbacks alive while the API holds them
        self.api._check(
            self.api.lib.sdrplay_api_Init(self.dev.dev, ctypes.byref(cbs), None), "sdrplay_api_Init"
        )
        self._running = True

    def stop(self) -> None:
        if self._running:
            self.api.lib.sdrplay_api_Uninit(self.dev.dev)
            self._running = False

    def close(self) -> None:
        self.stop()
        lib = self.api.lib
        lib.sdrplay_api_LockDeviceApi()
        try:
            lib.sdrplay_api_ReleaseDevice(ctypes.byref(self.dev))
        finally:
            lib.sdrplay_api_UnlockDeviceApi()

    def counter_info(self) -> dict:
        return {
            "counter_bits": 32,
            "unwrapped_to_bits": 64,
            "counter_step": [u.step for u in self._unwrap],
        }
