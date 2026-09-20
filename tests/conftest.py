import json
from pathlib import Path

import pytest

from ksm2sdvx.chart import KsonChart, load_kson
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.effects import EffectPair, LaserBitCrusher, NoEffect, ParameterAssignment
from ksm2sdvx.chart.vox.model import VoxBpmEvent, VoxChart, VoxMeterEvent, VoxPosition, VoxTrack


@pytest.fixture
def fixture_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def minimal_chart(fixture_root: Path) -> KsonChart:
    return load_kson(fixture_root / "kson/minimal.kson").chart


@pytest.fixture
def vox_chart() -> VoxChart:
    """A standalone target; serializer tests must not require KSON conversion."""
    start = VoxPosition(1, 1, VoxTick(0))
    return VoxChart(
        meters=(VoxMeterEvent(start, 4, 4),),
        bpms=(VoxBpmEvent(start, 120),),
        tilt_modes=(),
        tracks=tuple(VoxTrack(i, ()) for i in range(1, 9)),
        original_left=(),
        original_right=(),
        controllers=(),
        end_position=VoxPosition(17, 1, VoxTick(0)),
        laser_effects=tuple(LaserBitCrusher(0, 1) for _ in range(5)),
        fx_effects=tuple(EffectPair(NoEffect(), NoEffect()) for _ in range(12)),
        parameter_assignments=tuple(ParameterAssignment(i // 2) for i in range(24)),
    )


def document(**overrides: object) -> str:
    data: dict[str, object] = {
        "format_version": 1,
        "meta": {
            "title": "Synthetic",
            "artist": "Tests",
            "chart_author": "Tests",
            "difficulty": 2,
            "level": 10,
            "disp_bpm": "120",
        },
        "beat": {"bpm": [[0, 120]]},
    }
    data.update(overrides)
    return json.dumps(data)
