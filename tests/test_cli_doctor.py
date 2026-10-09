"""``reapet doctor`` against a missing or stubbed SDRplay API library."""

import ctypes

import pytest

from reapet import sdrplay
from reapet.cli import main


class StubLib:
    """Mimics the SDRplay API library functions that doctor calls before a device is used."""

    def __init__(self, version=3.15, devices=()):
        self._version = version
        self._devices = devices
        self.closed = False

        def ok(*a):
            return 0

        self.sdrplay_api_Open = ok
        self.sdrplay_api_LockDeviceApi = ok
        self.sdrplay_api_UnlockDeviceApi = ok
        self.sdrplay_api_SelectDevice = ok
        self.sdrplay_api_ReleaseDevice = ok
        self.sdrplay_api_GetDeviceParams = ok
        self.sdrplay_api_Init = ok
        self.sdrplay_api_Uninit = ok
        self.sdrplay_api_Update = ok
        self.sdrplay_api_GetErrorString = lambda err: b"stub error"
        self.sdrplay_api_GetLastError = lambda dev: None

        def close():
            self.closed = True
            return 0

        def version(ptr):
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_float))[0] = self._version
            return 0

        def get_devices(arr, n, maxn):
            for i, d in enumerate(self._devices):
                arr[i] = d
            ctypes.cast(n, ctypes.POINTER(ctypes.c_uint))[0] = len(self._devices)
            return 0

        self.sdrplay_api_Close = close
        self.sdrplay_api_ApiVersion = version
        self.sdrplay_api_GetDevices = get_devices


@pytest.fixture
def stub_api(monkeypatch):
    def install(lib):
        monkeypatch.setattr(
            sdrplay.SdrplayApi, "load", classmethod(lambda cls, c=None: cls(lib, "stub"))
        )
        return lib

    return install


def test_doctor_without_api_explains_installation(monkeypatch, capsys):
    monkeypatch.setenv("REAPET_SDRPLAY_API", "/nonexistent/libsdrplay_api.so")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "SDRplay API library not found" in out
    assert "sdrplay.com/api" in out


def test_doctor_with_unsupported_version_stops(stub_api, capsys):
    lib = stub_api(StubLib(version=3.07))
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "3.07" in out and "not supported" in out
    assert lib.closed


def test_doctor_without_devices_reports_version(stub_api, capsys):
    stub_api(StubLib(devices=()))
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "SDRplay API version: 3.15" in out
    assert "No device found" in out


def test_doctor_reports_rsp_without_dual_tuner(stub_api, capsys):
    d = sdrplay.DeviceT()
    d.SerNo = b"1234"
    d.hwVer = 255  # RSP1A, single tuner
    stub_api(StubLib(devices=(d,)))
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "RSP1A" in out and "no RSPduo found" in out
