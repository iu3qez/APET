"""Where the tuner and the stored narrow slice sit on each band (R4, KTD6).

The narrow slice (62.5 kS/s, alias-free over ±25 kHz) holds the FT8 subband
(dial frequency to dial + 3 kHz, USB) and a 3 kHz "quiet" slice nearby that the
IARU Region 1 band plan does not assign to digital modes. The quiet slices are
nominal: on a contest weekend they can carry CW or SSB, and the analysis decides
from the data whether they are usable.

The tuner is centred ``LO_OFFSET_HZ`` below the slice, so the slice never falls
on the DC spur and the whole amateur band stays inside the wide capture.
"""

from __future__ import annotations

from dataclasses import dataclass

LO_OFFSET_HZ = 200_000
NARROW_RATE = 62_500
NARROW_PASSBAND_HZ = 25_000


@dataclass(frozen=True)
class Band:
    name: str
    ft8_dial_hz: int
    quiet_hz: tuple[int, int]
    band_edges_hz: tuple[int, int]

    @property
    def ft8_hz(self) -> tuple[int, int]:
        return (self.ft8_dial_hz, self.ft8_dial_hz + 3_000)

    @property
    def slice_center_hz(self) -> int:
        lo = min(self.ft8_hz[0], self.quiet_hz[0])
        hi = max(self.ft8_hz[1], self.quiet_hz[1])
        return (lo + hi) // 2

    @property
    def tuner_center_hz(self) -> int:
        return self.slice_center_hz - LO_OFFSET_HZ

    def as_dict(self) -> dict:
        return {
            "band": self.name,
            "ft8_hz": list(self.ft8_hz),
            "quiet_hz": list(self.quiet_hz),
            "quiet_slice_nominal": True,
            "band_edges_hz": list(self.band_edges_hz),
            "slice_center_hz": self.slice_center_hz,
            "tuner_center_hz": self.tuner_center_hz,
        }


BANDS = {
    b.name: b
    for b in (
        Band("160m", 1_840_000, (1_850_000, 1_853_000), (1_810_000, 2_000_000)),
        Band("80m", 3_573_000, (3_555_000, 3_558_000), (3_500_000, 3_800_000)),
        Band("40m", 7_074_000, (7_095_000, 7_098_000), (7_000_000, 7_200_000)),
        Band("30m", 10_136_000, (10_120_000, 10_123_000), (10_100_000, 10_150_000)),
        Band("20m", 14_074_000, (14_115_000, 14_118_000), (14_000_000, 14_350_000)),
        Band("17m", 18_100_000, (18_115_000, 18_118_000), (18_068_000, 18_168_000)),
        Band("15m", 21_074_000, (21_050_000, 21_053_000), (21_000_000, 21_450_000)),
        Band("12m", 24_915_000, (24_940_000, 24_943_000), (24_890_000, 24_990_000)),
        Band("10m", 28_074_000, (28_050_000, 28_053_000), (28_000_000, 29_700_000)),
    )
}
