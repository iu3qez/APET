from reapet.acquisition import BlockQueue
from reapet.device import TunerConfig
from reapet.fake_device import FakeDevice, FakeScenario, Tone
from reapet.gain import propose_gain

FS = 2_000_000


def _propose(scenario, margin_db=10.0):
    dev = FakeDevice(scenario, speed=float("inf"))
    steps = dev.gain_steps(0, "50ohm")
    dev.configure(TunerConfig(14e6, FS, 1.536e6, steps[0], "50ohm"))
    q = BlockQueue(FS)
    p = propose_gain(
        dev,
        q,
        steps,
        fs=FS,
        full_scale=32767,
        margin_db=margin_db,
        settle_s=0.01,
        measure_s=0.02,
        pump=lambda: dev.produce(q, 4),
    )
    return p, steps, dev


def test_step_just_below_the_margin_is_chosen():
    # tone at -2 dBFS at the highest gain; -10 dBFS needs 8 dB more reduction: 20 -> 29 dB
    p, steps, _ = _propose(FakeScenario(tones=(Tone(10e3, -2.0),), noise_dbfs=-80))
    assert p.margin_met
    assert p.step.total_gr_db == 29
    assert all(not m["margin_met"] for m in p.measurements[:-1])


def test_stronger_channel_sets_the_gain_for_both():
    sc = FakeScenario(tones=(Tone(10e3, -15.0),), noise_dbfs=-80, level_offset_db=(0.0, 9.0))
    p, _, dev = _propose(sc)
    assert p.margin_met
    a, b = p.measurements[-1]["peak_dbfs"]
    assert b <= -10 and b > a
    rb = dev.readback()
    assert rb[0].if_gr_db == rb[1].if_gr_db == p.step.if_gr_db


def test_overload_rejects_a_step():
    sc = FakeScenario(tones=(Tone(10e3, -20.0),), noise_dbfs=-80, overload_above_dbfs=-25.0)
    p, _, _ = _propose(sc)
    assert p.margin_met
    assert p.measurements[0]["overload"] == [True, True]
    assert p.step.total_gr_db >= 26


def test_margin_not_met_uses_minimum_gain():
    p, steps, _ = _propose(FakeScenario(clipping=((0, 0.0, 1000.0),)))
    assert not p.margin_met
    assert p.step == steps[-1]
    assert len(p.measurements) == len(steps)
