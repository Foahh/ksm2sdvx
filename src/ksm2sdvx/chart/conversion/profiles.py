"""Explicit target capability."""

from dataclasses import dataclass

from ksm2sdvx.chart.errors import UnsupportedFormatError
from ksm2sdvx.chart.vox.effects import LaserBitCrusher, LaserEffect, LaserHighPass, LaserLowPass


@dataclass(frozen=True, slots=True)
class VoxProfile:
    name: str = "vox13"
    version: int = 13
    radius_anchors: tuple[float, float, float] = (17.12, 60.12, 110.12)
    rotation_anchors: tuple[float, float, float] = (0.28, 0.72, 1.57)
    # Definitions for the five laser effect slots.
    laser_effects: tuple[LaserEffect, ...] = (
        LaserLowPass(90, 400, 18000, 0.7),
        LaserLowPass(90, 600, 15000, 5),
        LaserHighPass(90, 40, 5000, 0.7),
        LaserHighPass(90, 40, 2000, 3),
        LaserBitCrusher(100, 30),
    )

    def validate(self) -> None:
        if self != VoxProfile():
            raise UnsupportedFormatError("Only the vox13 profile is implemented")


DEFAULT_PROFILE = VoxProfile()
