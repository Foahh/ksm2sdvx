from dataclasses import replace
from typing import cast

import pytest

from ksm2sdvx.chart import serialize_vox
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.effects import (
    BitCrusher,
    Echo,
    EffectPair,
    Flanger,
    FxEffect,
    Gate,
    HighPass,
    LaserBitCrusher,
    LaserHighPass,
    LaserLowPass,
    LowPass,
    NoEffect,
    ParameterAssignment,
    PitchAndSpeed,
    PitchShift,
    Retrigger,
    SideChain,
    TapeStop,
    TapeStopEx,
    Wobble,
)
from ksm2sdvx.chart.vox.model import AutoTabEvent, VoxChart, VoxFxChip, VoxFxHold, VoxPosition
from ksm2sdvx.chart.vox.serializer import effect_row


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (NoEffect(), "0,\t0,\t0,\t0,\t0,\t0,\t0"),
        (Retrigger(4, 95, 2, 1, 0.85, 0.15), "1,\t4,\t95.00,\t2.00,\t1.00,\t0.85,\t0.15"),
        (Gate(98, 8, 1), "2,\t98.00,\t8,\t1.00"),
        (Flanger(75, 2, 0.5, 90, 2), "3,\t75.00,\t2.00,\t0.50,\t90,\t2.00"),
        (TapeStop(100, 0.125, 1), "4,\t100.00,\t0.125,\t1.00"),
        (SideChain(95, 1, 2, 3, 4), "5,\t95.00,\t1.00,\t2,\t3,\t4"),
        (
            Wobble(1, 2, 80, 0.5, 100, 1000, 1.4),
            "6,\t1,\t2,\t80.00,\t0.50,\t100.00,\t1000.00,\t1.40",
        ),
        (BitCrusher(50, 12), "7,\t50.00,\t12"),
        (Echo(4, 95, 2, 1, 0.85, 0.15, 0), "8,\t4,\t95.00,\t2.00,\t1.00,\t0.85,\t0.15,\t0.00"),
        (PitchShift(100, -7), "9,\t100.00,\t-7.00"),
        (TapeStopEx(1, 2, 3, 4, 5), "10,\t1.00,\t2.00,\t3.00,\t4.00,\t5.00"),
        (LowPass(90, 400, 18000, 0.7), "11,\t90.00,\t400.00,\t18000.00,\t0.70"),
        (HighPass(90, 40, 5000, 0.7), "12,\t90.00,\t40.00,\t5000.00,\t0.70"),
        (PitchAndSpeed(100, 0, 1), "13,\t100.00,\t0.00,\t1.00"),
    ],
)
def test_fx_effect_column_order_and_types(
    vox_chart: VoxChart, effect: FxEffect, expected: str
) -> None:
    target = replace(
        vox_chart, fx_effects=(EffectPair(effect, NoEffect()), *vox_chart.fx_effects[1:])
    )
    assert expected in serialize_vox(target).splitlines()


def test_laser_effect_table_column_types() -> None:
    assert (
        effect_row(LaserLowPass(90, 400, 18000, 0.7), laser=True)
        == "1,\t90.00,\t400.00,\t18000.00,\t0.70"
    )
    assert (
        effect_row(LaserHighPass(90, 40, 5000, 0.7), laser=True)
        == "2,\t90.00,\t40.00,\t5000.00,\t0.70"
    )
    assert effect_row(LaserBitCrusher(100, 30), laser=True) == "3,\t100.00,\t30"


def test_effect_references_and_descending_parameter_sweep(vox_chart: VoxChart) -> None:
    start = VoxPosition(1, 1, VoxTick(0))
    target = replace(
        vox_chart,
        fx_effects=(
            *vox_chart.fx_effects[:6],
            EffectPair(Flanger(75, 2, 3, 90, 2), NoEffect()),
            *vox_chart.fx_effects[7:],
        ),
        parameter_assignments=(
            *vox_chart.parameter_assignments[:12],
            ParameterAssignment(6, 3, 3, 0.5),
            *vox_chart.parameter_assignments[13:],
        ),
        auto_tab=(AutoTabEvent(start, VoxTick(96), 8),),
    )
    text = serialize_vox(target)
    assert "6,\t3,\t3.00,\t0.50" in text
    assert "#TRACK AUTO TAB\n001,01,00\t96\t8\n" in text


@pytest.mark.parametrize("index", [0, 1, 14, 255])
def test_invalid_fx_pair_indices(vox_chart: VoxChart, index: int) -> None:
    start = VoxPosition(1, 1, VoxTick(0))
    with pytest.raises(ConversionError, match="2-indexed"):
        serialize_vox(replace(vox_chart, auto_tab=(AutoTabEvent(start, VoxTick(48), index),)))
    tracks = tuple(
        replace(t, events=(VoxFxHold(start, VoxTick(48), index),)) if t.number == 2 else t
        for t in vox_chart.tracks
    )
    with pytest.raises(ConversionError, match="2-indexed"):
        serialize_vox(replace(vox_chart, tracks=tracks))


@pytest.mark.parametrize("sample", [0, 1, 14, 255])
def test_chip_sample_is_independent_of_effect_pair(vox_chart: VoxChart, sample: int) -> None:
    chip = VoxFxChip(VoxPosition(1, 1, VoxTick(0)), sample, 12)
    tracks = tuple(replace(t, events=(chip,)) if t.number == 7 else t for t in vox_chart.tracks)
    assert f"#TRACK7\n001,01,00\t0\t{sample}\t12" in serialize_vox(
        replace(vox_chart, tracks=tracks)
    )


def test_invalid_effect_tables(vox_chart: VoxChart) -> None:
    for invalid in (
        replace(vox_chart, laser_effects=vox_chart.laser_effects[:-1]),
        replace(vox_chart, fx_effects=vox_chart.fx_effects[:-1]),
        replace(vox_chart, parameter_assignments=vox_chart.parameter_assignments[:-1]),
        replace(
            vox_chart,
            parameter_assignments=(ParameterAssignment(1), *vox_chart.parameter_assignments[1:]),
        ),
        replace(
            vox_chart,
            parameter_assignments=(
                ParameterAssignment(0, 99),
                *vox_chart.parameter_assignments[1:],
            ),
        ),
        replace(
            vox_chart,
            fx_effects=(
                EffectPair(Gate(100, cast(int, 2.5), 1), NoEffect()),
                *vox_chart.fx_effects[1:],
            ),
        ),
        replace(
            vox_chart,
            laser_effects=(LaserBitCrusher(float("nan"), 1), *vox_chart.laser_effects[1:]),
        ),
    ):
        with pytest.raises(ConversionError):
            serialize_vox(invalid)
