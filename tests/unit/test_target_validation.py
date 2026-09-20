from dataclasses import replace

import pytest

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    KsonChart,
    convert_chart,
    serialize_vox,
)
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, VoxBtNote, VoxPosition


@pytest.mark.parametrize(
    "position",
    [VoxPosition(0, 1, VoxTick(0)), VoxPosition(1, 5, VoxTick(0)), VoxPosition(1, 1, VoxTick(48))],
)
def test_out_of_meter_positions(minimal_chart: KsonChart, position: VoxPosition) -> None:
    target = convert_chart(
        minimal_chart, options=ConversionOptions(), profile=DEFAULT_PROFILE
    ).chart
    with pytest.raises(ConversionError):
        serialize_vox(replace(target, end_position=position))


def test_button_duration_cannot_exceed_chart(minimal_chart: KsonChart) -> None:
    target = convert_chart(
        minimal_chart, options=ConversionOptions(), profile=DEFAULT_PROFILE
    ).chart
    button = VoxBtNote(target.end_position, VoxTick(48), 2)
    tracks = tuple(replace(t, events=(button,)) if t.number == 3 else t for t in target.tracks)
    with pytest.raises(ConversionError, match="duration"):
        serialize_vox(replace(target, tracks=tracks))


def test_controller_duration_cannot_exceed_chart(minimal_chart: KsonChart) -> None:
    target = convert_chart(
        minimal_chart, options=ConversionOptions(), profile=DEFAULT_PROFILE
    ).chart
    span = ControllerSpan(target.end_position, ControllerName.RADIUS, VoxTick(48), 0.0, 1.0)
    with pytest.raises(ConversionError, match="duration"):
        serialize_vox(replace(target, controllers=(*target.controllers, span)))


def test_invalid_bpm_and_modes(minimal_chart: KsonChart) -> None:
    target = convert_chart(
        minimal_chart, options=ConversionOptions(), profile=DEFAULT_PROFILE
    ).chart
    with pytest.raises(ConversionError):
        serialize_vox(replace(target, bpms=(replace(target.bpms[0], bpm=float("nan")),)))
    with pytest.raises(ConversionError):
        serialize_vox(replace(target, tilt_modes=(replace(target.tilt_modes[0], mode=99),)))
