import pytest

from reapet.cli import main
from reapet.device import (
    LockedError,
    ReadbackMismatch,
    TunerConfig,
    common_input,
    missing_capabilities,
)
from reapet.fake_device import FakeDevice, FakeScenario


def _config(dev, inp="50ohm"):
    step = dev.gain_steps(14e6, inp)[0]
    return TunerConfig(14e6, 2e6, 1.536e6, step, inp)


def test_single_receiver_refused_naming_capability():  # AE5
    missing = missing_capabilities(FakeDevice(FakeScenario(receivers=1)).capabilities())
    assert any("two receivers" in m for m in missing)


def test_non_simultaneous_receivers_refused():  # AE5
    missing = missing_capabilities(FakeDevice(FakeScenario(same_clock=False)).capabilities())
    assert missing == ["simultaneous reception on one clock with a sample counter"]


def test_no_manual_gain_refused():
    missing = missing_capabilities(FakeDevice(FakeScenario(manual_gain=False)).capabilities())
    assert missing == ["manual gain"]


def test_agc_that_cannot_be_disabled_refused():
    missing = missing_capabilities(FakeDevice(FakeScenario(agc_can_disable=False)).capabilities())
    assert missing == ["AGC that can be disabled"]


def test_lock_reads_back_equal_settings_agc_off():
    dev = FakeDevice()
    dev.configure(_config(dev))
    readbacks = dev.lock()
    assert [rb.channel for rb in readbacks] == ["A", "B"]
    assert readbacks[0].if_gr_db == readbacks[1].if_gr_db
    assert readbacks[0].lna_state == readbacks[1].lna_state
    assert not any(rb.agc_enabled for rb in readbacks)


def test_readback_difference_on_b_is_reported_and_not_locked():
    dev = FakeDevice(FakeScenario(readback_offset_b={"if_gr_db": 1}))
    dev.configure(_config(dev))
    with pytest.raises(ReadbackMismatch) as e:
        dev.lock()
    assert "if_gr_db" in str(e.value)
    assert not dev.locked


def test_gain_change_after_lock_refused():
    dev = FakeDevice()
    dev.configure(_config(dev))
    dev.lock()
    with pytest.raises(LockedError):
        dev.set_gain(dev.gain_steps(14e6, "50ohm")[3])
    with pytest.raises(LockedError):
        dev.configure(_config(dev))


def test_different_inputs_use_the_common_type():
    caps = FakeDevice(FakeScenario(inputs=(("hiz", "50ohm"), ("50ohm",)))).capabilities()
    assert common_input(caps) == "50ohm"
    dev = FakeDevice(FakeScenario(inputs=(("hiz", "50ohm"), ("50ohm",))))
    dev.configure(_config(dev, common_input(caps)))
    assert {rb.input for rb in dev.lock()} == {"50ohm"}


def test_no_common_input_refused():
    caps = FakeDevice(FakeScenario(inputs=(("hiz",), ("50ohm",)))).capabilities()
    assert missing_capabilities(caps) == ["an input type available on both receivers"]


def test_doctor_with_simulated_device(capsys):
    assert main(["doctor", "--fake", "--seconds", "0.3"]) == 0
    out = capsys.readouterr().out
    assert "Receivers: 2" in out
    assert "2 MS/s" in out
    assert "ci16_le" in out
    assert "lag 0 samples" in out
