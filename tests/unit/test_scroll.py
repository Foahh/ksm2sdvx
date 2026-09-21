from dataclasses import replace
from typing import cast

import pytest
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    parse_kson,
    serialize_vox,
)
from ksm2sdvx.chart.conversion.converter import ConversionResult
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.model import ManualSpeed, VoxChart, VoxPosition
from ksm2sdvx.chart.vox.validation import Positions, validate_vox
from ksm2sdvx.common.diagnostics import FeatureStatus


def convert(points: object, *, step: int = 15, strict: bool = True) -> ConversionResult:
    return convert_chart(
        parse_kson(document(beat={"bpm": [[0, 120]], "scroll_speed": points})).chart,
        options=ConversionOptions(curve_step=step, strict=strict),
        profile=DEFAULT_PROFILE,
    )


def samples(result: ConversionResult) -> list[tuple[int, float]]:
    positions = Positions(result.chart.meters)
    return [
        (int(positions.absolute(e.position)) * 5, e.multiplier)
        for e in result.chart.controllers
        if isinstance(e, ManualSpeed)
    ]


@pytest.mark.parametrize("points", [[], [[0, 1]], [[0, 1], [240, 1, [0.5, 0]]]])
def test_default_speed_needs_no_controller(points: object) -> None:
    result = convert(points)
    assert samples(result) == []
    assert result.report.counts["scroll_speed_rows"] == 0
    assert not any(d.feature == "scroll_speed" for d in result.report.diagnostics)


def test_jumps_zero_large_values_and_final_hold() -> None:
    result = convert([[0, 2], [240, [2, 1000]], [270, [1000, 0]], [480, [0, 1]]])
    assert samples(result) == [(0, 2), (240, 1000), (270, 0), (480, 1)]
    assert result.report.end_pulse == 480
    assert result.chart.end_position == VoxPosition(1, 3, VoxTick(0))
    assert all(f.status != FeatureStatus.UNSUPPORTED for f in result.report.features)
    text = serialize_vox(result.chart)
    assert "001,02,06\tManualSpeed\t0\t0\tf0.00\t0.00\t0.00\t0.00" in text
    assert "SAMPLED_SCROLL_SPEED" not in {d.code for d in result.report.diagnostics}


def test_delayed_first_point_holds_incoming_before_jump() -> None:
    assert samples(convert([[240, [2, 3]]])) == [(0, 2), (240, 3)]
    assert samples(convert([[240, 2]])) == [(0, 2)]
    assert samples(convert([[0, [2, 3]]])) == [(0, 3)]


def test_linear_ramp_is_sampled_and_endpoint_jump_wins() -> None:
    result = convert([[0, 1], [60, [2, 0]], [120, 0]])
    assert samples(result) == [(15, 1.25), (30, 1.5), (45, 1.75), (60, 0)]
    assert not result.report.diagnostics
    assert next(f for f in result.report.features if f.feature == "scroll_speed").status == (
        FeatureStatus.APPROXIMATED
    )


def test_quadratic_curve_and_custom_sampling_interval() -> None:
    points = [[0, 1, [0.5, 0]], [60, 2]]
    assert samples(convert(points)) == [(15, 1.0625), (30, 1.25), (45, 1.5625), (60, 2)]
    assert samples(convert(points, step=20)) == pytest.approx(
        [(20, 1 + 1 / 9), (40, 1 + 4 / 9), (60, 2)]
    )


def test_short_ramp_keeps_endpoint_and_last_control_has_no_span() -> None:
    assert samples(convert([[0, 0], [5, 1, [0.5, 0]]])) == [(0, 0), (5, 1)]
    result = convert([[0, 2, [0.5, 0]]])
    assert samples(result) == [(0, 2)]
    assert "SAMPLED_SCROLL_SPEED" not in {d.code for d in result.report.diagnostics}


def test_bpm_and_meter_changes_do_not_rescale_multipliers_or_note_times() -> None:
    chart = parse_kson(
        document(
            beat={
                "bpm": [[0, 120], [960, 240]],
                "time_sig": [[0, [4, 4]], [1, [3, 8]]],
                "scroll_speed": [[0, 1], [960, [1, 0.5]], [1320, [0.5, 1]]],
            },
            note={"bt": [[1080], [], [], []]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    assert samples(result) == [(960, 0.5), (1320, 1)]
    assert result.chart.bpms[-1].bpm == 240
    assert result.chart.tracks[2].events[0].position == VoxPosition(2, 2, VoxTick(0))
    assert result.chart.end_position == VoxPosition(3, 1, VoxTick(0))


@pytest.mark.parametrize("points", [[[6, 2]], [[0, 1], [6, 1]], [[0, 1], [16, 2]]])
def test_off_grid_anchors_are_rejected(points: object) -> None:
    with pytest.raises(ConversionError, match="five-pulse grid"):
        convert(points)


@pytest.mark.parametrize("strict", [False, True])
def test_negative_speed_jumps_preserve_whole_graph(strict: bool) -> None:
    result = convert([[0, 2], [240, [2, -1]], [480, [-1, 1]]], strict=strict)
    assert samples(result) == [(0, 2), (240, -1), (480, 1)]
    assert result.report.end_pulse == 480
    assert not any(d.feature == "scroll_speed" for d in result.report.diagnostics)
    assert "001,02,00\tManualSpeed\t0\t0\tf-1.00\t0.00\t0.00\t0.00" in serialize_vox(result.chart)


def test_delayed_negative_speed_holds_before_first_anchor_and_after_last() -> None:
    result = convert([[240, [-2, -1]]])
    assert samples(result) == [(0, -2), (240, -1)]
    assert result.report.end_pulse == 240


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([[0, 1], [60, -1]], [(15, 0.5), (30, 0), (45, -0.5), (60, -1)]),
        (
            [[0, -1, [0.5, 0]], [60, 1]],
            [(0, -1), (15, -0.875), (30, -0.5), (45, 0.125), (60, 1)],
        ),
    ],
)
def test_signed_ramps_cross_zero(points: object, expected: list[tuple[int, float]]) -> None:
    result = convert(points)
    assert samples(result) == expected
    assert not result.report.diagnostics


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("value", [0.125, -0.125])
def test_typed_manual_speed_wire_format(vox_chart: VoxChart, locked: bool, value: float) -> None:
    event = ManualSpeed(VoxPosition(2, 1, VoxTick(0)), value, unknown_c2=0x80000000)
    target = (
        replace(vox_chart, locked_controllers=(event,))
        if locked
        else replace(vox_chart, controllers=(event,))
    )
    text = serialize_vox(target)
    section = "LOCKED_SPCONTROLER" if locked else "SPCONTROLER"
    assert f"#{section}\n002,01,00\tManualSpeed\t2147483648\t0\tf{value}\t0.00\t0.00\t0.00" in text


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), 1e40, -1e40, cast(float, True)]
)
def test_manual_speed_rejects_invalid_payload(vox_chart: VoxChart, value: float) -> None:
    event = ManualSpeed(VoxPosition(1, 1, VoxTick(0)), value)
    with pytest.raises(ConversionError):
        validate_vox(replace(vox_chart, controllers=(event,)))


def test_manual_speed_must_be_within_chart(vox_chart: VoxChart) -> None:
    event = ManualSpeed(VoxPosition(18, 1, VoxTick(0)), 1)
    with pytest.raises(ConversionError, match="exceeds end position"):
        validate_vox(replace(vox_chart, controllers=(event,)))
