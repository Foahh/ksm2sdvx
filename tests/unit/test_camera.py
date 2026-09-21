from dataclasses import replace
from itertools import pairwise
from math import inf, nan

import pytest
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    parse_kson,
    serialize_vox,
)
from ksm2sdvx.chart.conversion.camera import rebase_tilt
from ksm2sdvx.chart.conversion.converter import ConversionResult
from ksm2sdvx.chart.conversion.zoom import ZoomGraph, zoom_spans
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.geometry.camera import (
    MANUAL_TILT_SCALE,
    Normalization,
    source_landmarks,
    target_landmarks,
    zoom_pose,
)
from ksm2sdvx.chart.kson.model import AutoTilt, CurveControl, GraphPoint, TiltEvent
from ksm2sdvx.chart.types import KsonPulse, VoxTick
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, Realize, TiltNode, VoxPosition
from ksm2sdvx.common.diagnostics import FeatureStatus

RADIUS = Normalization(*DEFAULT_PROFILE.radius_anchors)
ROTATION = Normalization(*DEFAULT_PROFILE.rotation_anchors)


def camera_result(camera: object, options: ConversionOptions | None = None) -> ConversionResult:
    return convert_chart(
        parse_kson(document(camera=camera)).chart,
        options=options or ConversionOptions(),
        profile=DEFAULT_PROFILE,
    )


def spans(result: ConversionResult, name: ControllerName) -> list[ControllerSpan]:
    return [c for c in result.chart.controllers if isinstance(c, ControllerSpan) and c.name == name]


def test_default_camera_initialization() -> None:
    result = camera_result({})
    initializers = [c for c in result.chart.controllers if isinstance(c, Realize)]
    assert [(c.controller, c.c4, c.c5, c.c6) for c in initializers] == [
        (3, 17.12, 60.12, 110.12),
        (4, 0.28, 0.72, 1.57),
    ]
    assert len(result.chart.controllers) == 4


def test_realize_precedes_pulse_zero_joint_camera_jump() -> None:
    result = camera_result(
        {
            "cam": {
                "body": {
                    "zoom_bottom": [[0, [0, 100]], [240, 0]],
                    "zoom_top": [[0, [0, 100]], [240, 0]],
                }
            }
        }
    )
    assert isinstance(result.chart.controllers[0], Realize)
    assert isinstance(result.chart.controllers[1], Realize)
    radii, angles = spans(result, ControllerName.RADIUS), spans(result, ControllerName.ROTATION_X)
    assert radii[0].duration == angles[0].duration == 0
    actual = target_landmarks(
        RADIUS.decode(radii[0].end_value), ROTATION.decode(angles[0].end_value)
    )
    neutral = target_landmarks(RADIUS.middle, ROTATION.middle)
    source, base = source_landmarks(100, 100), source_landmarks(0, 0)
    assert (actual[0] / neutral[0], actual[1] / neutral[1]) == pytest.approx(
        (source[0] / base[0], source[1] / base[1])
    )


@pytest.mark.parametrize(
    "bottom,ratio",
    [
        (-200, 0.41196485),
        (-50, 0.73661442),
        (100, 1.40133331),
        (200, 2.34243678),
        (300, 7.14802557),
    ],
)
def test_zoom_width_uses_projection_across_signed_values(bottom: float, ratio: float) -> None:
    pose = zoom_pose(bottom, 0, RADIUS, ROTATION)
    assert RADIUS.middle / pose.radius == pytest.approx(ratio)
    assert pose.height == pytest.approx(zoom_pose(0, 0, RADIUS, ROTATION).height)
    assert RADIUS.decode(RADIUS.encode(pose.radius)) == pytest.approx(pose.radius)
    assert ROTATION.decode(ROTATION.encode(pose.pitch)) == pytest.approx(pose.pitch)


def test_bottom_control_also_adjusts_pitch() -> None:
    positive, negative = (zoom_pose(v, 0, RADIUS, ROTATION) for v in (100, -100))
    assert positive.pitch < ROTATION.middle < negative.pitch
    assert abs(RADIUS.encode(negative.radius)) > 2 * abs(RADIUS.encode(positive.radius))


@pytest.mark.parametrize("top", [-200, 100, 300, 500, 2400])
def test_top_adjusts_width_and_height_jointly(top: float) -> None:
    pose = zoom_pose(0, top, RADIUS, ROTATION)
    target = target_landmarks(pose.radius, pose.pitch)
    base = target_landmarks(RADIUS.middle, ROTATION.middle)
    source, neutral = source_landmarks(0, top), source_landmarks(0, 0)
    assert (target[0] / base[0], target[1] / base[1]) == pytest.approx(
        (source[0] / neutral[0], source[1] / neutral[1])
    )


@pytest.mark.parametrize(
    "bottom,top",
    [(400, 0), (0, -300), (0, 800), (0, 1200), (0, 1600), (nan, 0), (0, inf), (0, 1e300)],
)
def test_unrepresentable_projection_is_rejected(bottom: float, top: float) -> None:
    with pytest.raises(ConversionError):
        zoom_pose(bottom, top, RADIUS, ROTATION)


def test_normalization_inverts_anchors_and_rejects_turning_point() -> None:
    for normalization in (RADIUS, ROTATION):
        for encoded, physical in zip(
            (-1, 0, 1), (normalization.low, normalization.middle, normalization.high), strict=True
        ):
            assert normalization.encode(physical) == pytest.approx(encoded)
        turning = normalization.middle - normalization.linear**2 / (4 * normalization.quadratic)
        with pytest.raises(ConversionError, match="normalization branch"):
            normalization.encode(turning - 1)


def test_staggered_graphs_hold_values_at_other_graphs_knots() -> None:
    result = camera_result(
        {
            "cam": {
                "body": {
                    "zoom_bottom": [[0, 0], [240, 100]],
                    "zoom_top": [[120, 0], [360, 100]],
                }
            }
        }
    )
    radii, angles = spans(result, ControllerName.RADIUS), spans(result, ControllerName.ROTATION_X)
    assert [(s.position, s.duration) for s in radii] == [(s.position, s.duration) for s in angles]
    assert RADIUS.decode(radii[-1].end_value) == pytest.approx(
        zoom_pose(100, 100, RADIUS, ROTATION).radius
    )
    assert result.report.end_pulse == 1515


def test_isolated_zoom_value_is_initialized_and_held_before_first_point() -> None:
    result = camera_result({"cam": {"body": {"zoom_bottom": [[240, 100]]}}})
    radii = spans(result, ControllerName.RADIUS)
    assert radii[0].position.measure == 1 and radii[0].position.beat == 1
    assert radii[0].duration == 0
    assert radii[-1].start_value == radii[-1].end_value
    assert RADIUS.decode(radii[-1].end_value) == pytest.approx(
        zoom_pose(100, 0, RADIUS, ROTATION).radius
    )


def test_nonlinear_motion_is_checked_in_physical_interpolation_space() -> None:
    bottom = (
        GraphPoint(KsonPulse(0), -50, -50, CurveControl(0.2, 0.8)),
        GraphPoint(KsonPulse(960), 150, 150),
    )
    top = (GraphPoint(KsonPulse(0), -100, -100), GraphPoint(KsonPulse(960), 200, 200))
    rows = zoom_spans(bottom, top, RADIUS, ROTATION, 15)
    bg, tg = ZoomGraph(bottom), ZoomGraph(top)
    for row in rows:
        if not row.duration:
            continue
        assert row.duration <= 15 and row.duration % 5 == 0
        # Interpolate decoded endpoints, as a target reader does after serialization.
        r0, r1 = (RADIUS.decode(round(RADIUS.encode(p.radius), 9)) for p in (row.start, row.end))
        a0, a1 = (ROTATION.decode(round(ROTATION.encode(p.pitch), 9)) for p in (row.start, row.end))
        for i in range(1, 16):
            t = i / 16
            pulse = row.pulse + t * row.duration
            expected = zoom_pose(bg.value(pulse), tg.value(pulse), RADIUS, ROTATION)
            actual = target_landmarks(r0 + (r1 - r0) * t, a0 + (a1 - a0) * t)
            assert max(abs(actual[0] - expected.width), abs(actual[1] - expected.height)) < 0.251


def test_zero_crossing_retains_grid_knots() -> None:
    points = (GraphPoint(KsonPulse(0), -100, -100), GraphPoint(KsonPulse(600), 100, 100))
    rows = zoom_spans(points, (), RADIUS, ROTATION, 200)
    assert any(r.pulse == 300 for r in rows)
    assert all(r.pulse % 5 == r.duration % 5 == 0 for r in rows)


def test_top_turn_does_not_alias_matching_endpoints() -> None:
    with pytest.raises(ConversionError):
        camera_result({"cam": {"body": {"zoom_top": [[0, 0], [960, 2400]]}}})


def test_fast_zoom_that_exceeds_tick_precision_is_rejected() -> None:
    with pytest.raises(ConversionError, match="one VOX tick"):
        camera_result({"cam": {"body": {"zoom_bottom": [[0, 0], [5, 300]]}}})


@pytest.mark.parametrize("turn", [-72, -36, 36, 72])
def test_instantaneous_tilt_turn_is_removed_without_changing_following_ramp(turn: float) -> None:
    result = camera_result({"tilt": [[0, 0], [240, [0, turn]], [480, turn + 1]]})
    rows = spans(result, ControllerName.TILT)
    assert not any(row.duration == 0 for row in rows)
    assert rows[-2].start_value == 0
    assert rows[-2].end_value == rows[-1].start_value
    assert rows[-1].end_value == pytest.approx(MANUAL_TILT_SCALE)


@pytest.mark.parametrize("end", [-72, -36, 36, 72])
def test_continuous_tilt_turns_preserve_direction_and_winding(end: float) -> None:
    result = camera_result({"tilt": [[0, 0], [3840, end]]})
    rows = spans(result, ControllerName.TILT)
    assert rows[-1].end_value == pytest.approx(end * MANUAL_TILT_SCALE)
    assert f"{end * MANUAL_TILT_SCALE:.9f}" in serialize_vox(result.chart)


@pytest.mark.parametrize("values", [(35, 37), (37, 35), (-35, -37), (-37, -35)])
def test_tilt_ramp_across_turn_boundary_preserves_signed_distance(values: tuple[int, int]) -> None:
    result = camera_result({"tilt": [[0, values[0]], [960, values[1]]]})
    row = spans(result, ControllerName.TILT)[0]
    assert row.end_value - row.start_value == pytest.approx(
        (values[1] - values[0]) * MANUAL_TILT_SCALE
    )


def test_tilt_rebasing_resets_at_automatic_mode() -> None:
    points = (
        TiltEvent(KsonPulse(0), 0, 0),
        TiltEvent(KsonPulse(240), 0, 36),
        TiltEvent(KsonPulse(480), 37, AutoTilt.NORMAL),
        TiltEvent(KsonPulse(720), 0, 0),
        TiltEvent(KsonPulse(960), 1, 1),
    )
    changed = rebase_tilt(points)
    assert changed[2].incoming == 1
    assert changed[3:] == points[3:]
    assert (
        rebase_tilt((replace(points[0], incoming=AutoTilt.NORMAL, outgoing=36),))[0].outgoing == 0
    )


def test_separate_manual_sequences_restart_node_encoding() -> None:
    result = camera_result({"tilt": [[0, 0], [240, [1, "normal"]], [480, 0], [720, [1, "normal"]]]})
    assert [span.node_type for span in spans(result, ControllerName.TILT)] == [1, 1]


@pytest.mark.parametrize("value", [0, 2])
def test_single_manual_value_holds_during_lasers(value: int) -> None:
    chart = parse_kson(
        document(
            camera={"tilt": [[0, value]]},
            note={"laser": [[[0, [[0, 0], [480, 1], [960, 0]]]], []]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    rows = spans(result, ControllerName.TILT)
    assert len(rows) == 1
    row = rows[0]
    assert row.position == VoxPosition(1, 1, VoxTick(0))
    assert row.duration == 192
    assert row.node_type == TiltNode.SINGLE
    assert (row.start_value, row.end_value) == pytest.approx((value * MANUAL_TILT_SCALE,) * 2)
    assert result.report.end_pulse == 960


def test_final_manual_zero_holds_after_a_ramp() -> None:
    chart = parse_kson(
        document(
            camera={"tilt": [[0, 2], [240, 0]]},
            note={"laser": [[[0, [[0, 0], [480, 1], [960, 0]]]], []]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    first, hold = spans(result, ControllerName.TILT)
    assert first.node_type == TiltNode.START
    assert hold.node_type == TiltNode.END
    assert hold.position == VoxPosition(1, 2, VoxTick(0))
    assert hold.duration == 144
    assert hold.start_value == hold.end_value == 0


def test_manual_zero_releases_only_at_automatic_setting() -> None:
    chart = parse_kson(
        document(
            camera={"tilt": [[0, 0], [480, "normal"], [720, 0]]},
            note={"laser": [[[0, [[0, 0], [480, 1], [960, 0]]]], []]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    first, resumed = spans(result, ControllerName.TILT)
    assert first.node_type == resumed.node_type == TiltNode.SINGLE
    assert first.duration == 96
    assert resumed.position == VoxPosition(1, 4, VoxTick(0))
    assert resumed.duration == 48
    assert first.start_value == first.end_value == resumed.start_value == resumed.end_value == 0


@pytest.mark.parametrize("camera_end,expected_end", [(960, 1440), (1920, 3360)])
def test_manual_hold_covers_later_camera_and_timing_events(
    camera_end: int, expected_end: int
) -> None:
    chart = parse_kson(
        document(
            camera={"tilt": [[0, 0]], "cam": {"body": {"zoom_top": [[camera_end, 0]]}}},
            beat={"bpm": [[0, 120], [1440, 150]]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    assert spans(result, ControllerName.TILT)[0].duration == expected_end // 5
    assert result.report.end_pulse == expected_end


@pytest.mark.parametrize("value", [0, 1, -1, "zero"])
def test_terminal_tilt_has_a_hold_before_playback_ends(value: int | str) -> None:
    result = convert_chart(
        parse_kson(
            document(
                beat={"bpm": [[0, 120], [960, 185]]},
                note={"bt": [[960], [], [], []]},
                camera={"tilt": [[0, "normal"], [960, value]]},
            )
        ).chart,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
    )
    (hold,) = spans(result, ControllerName.TILT)
    assert hold.position == VoxPosition(2, 1, VoxTick(0))
    assert hold.duration == 356
    assert hold.node_type == TiltNode.SINGLE
    expected = value * MANUAL_TILT_SCALE if isinstance(value, int) else 0
    assert hold.start_value == hold.end_value == pytest.approx(expected)
    assert result.report.end_pulse == 2740
    serialize_vox(result.chart)


def test_terminal_zoom_and_tilt_share_the_outro_without_moving_notes() -> None:
    result = convert_chart(
        parse_kson(
            document(
                note={"bt": [[960], [], [], []]},
                camera={
                    "tilt": [[0, "normal"], [960, 1]],
                    "cam": {
                        "body": {
                            "zoom_top": [[0, 50], [960, [50, -100]]],
                            "zoom_bottom": [[0, 0], [960, [0, 100]]],
                        }
                    },
                },
            )
        ).chart,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
    )
    ending = VoxPosition(2, 1, VoxTick(0))
    assert result.chart.tracks[2].events[-1].position == ending
    for name in (ControllerName.RADIUS, ControllerName.ROTATION_X, ControllerName.TILT):
        assert spans(result, name)[-1].position == ending
    assert result.chart.end_position > ending
    assert result.report.end_pulse == 2115
    assert spans(result, ControllerName.TILT)[-1].duration == 231


def test_manual_jump_stays_inside_its_sequence() -> None:
    result = camera_result({"tilt": [[0, [0, 1]], [240, "normal"], [480, 0], [720, [0, "normal"]]]})
    jump, hold, resumed = spans(result, ControllerName.TILT)
    assert [jump.node_type, hold.node_type, resumed.node_type] == [
        TiltNode.START,
        TiltNode.END,
        TiltNode.SINGLE,
    ]
    assert jump.duration == 0
    assert jump.end_value == hold.start_value == hold.end_value
    assert hold.duration == resumed.duration == 48


def test_manual_curve_keeps_full_turn_without_sampling_warning() -> None:
    result = camera_result({"tilt": [[0, [0, [0.2, 0.8]]], [3840, 36]]})
    rows = spans(result, ControllerName.TILT)
    assert len(rows) > 2 and rows[-1].end_value == pytest.approx(36 * MANUAL_TILT_SCALE)
    assert all(a.end_value == b.start_value for a, b in pairwise(rows))
    assert "SAMPLED_TILT_CURVE" not in {d.code for d in result.report.diagnostics}


@pytest.mark.parametrize("mode, code", [("normal", 0), ("bigger", 1), ("keep_bigger", 2)])
def test_zero_tilt_holds_during_lasers_then_restores_automatic_mode(mode: str, code: int) -> None:
    chart = parse_kson(
        document(
            camera={"tilt": [[0, "zero"], [480, mode]]},
            note={"laser": [[[0, [[0, 0], [480, 1], [960, 0]]]], []]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    (hold,) = spans(result, ControllerName.TILT)
    assert hold.node_type == TiltNode.SINGLE
    assert hold.duration == 96
    assert hold.start_value == hold.end_value == 0
    assert result.chart.tilt_modes[-1].position == VoxPosition(1, 3, VoxTick(0))
    assert result.chart.tilt_modes[-1].mode == code
    assert not any(f.status == FeatureStatus.UNSUPPORTED for f in result.report.features)


def test_zero_tilt_between_manual_values_does_not_create_ramps() -> None:
    result = camera_result(
        {"tilt": [[0, 2], [240, "zero"], [480, 1], [720, "normal"]]},
        ConversionOptions(strict=True),
    )
    before, zero, after = spans(result, ControllerName.TILT)
    assert all(
        row.node_type == TiltNode.SINGLE and row.duration == 48 for row in (before, zero, after)
    )
    assert before.start_value == before.end_value == 2 * MANUAL_TILT_SCALE
    assert zero.start_value == zero.end_value == 0
    assert after.start_value == after.end_value == MANUAL_TILT_SCALE


def test_numeric_incoming_value_is_preserved_when_switching_to_zero() -> None:
    result = camera_result(
        {"tilt": [[0, 1], [240, [2, "zero"]], [480, "normal"]]},
        ConversionOptions(strict=True),
    )
    ramp, zero = spans(result, ControllerName.TILT)
    assert ramp.start_value == MANUAL_TILT_SCALE
    assert ramp.end_value == 2 * MANUAL_TILT_SCALE
    assert ramp.node_type == zero.node_type == TiltNode.SINGLE
    assert zero.position == VoxPosition(1, 2, VoxTick(0))
    assert zero.duration == 48
    assert zero.start_value == zero.end_value == 0


def test_zero_tilt_final_hold_reaches_last_note() -> None:
    chart = parse_kson(
        document(camera={"tilt": [[240, "zero"]]}, note={"bt": [[960], [], [], []]})
    ).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    (zero,) = spans(result, ControllerName.TILT)
    assert zero.position == VoxPosition(1, 2, VoxTick(0))
    assert zero.duration == 144
    assert zero.start_value == zero.end_value == 0


def test_zero_tilt_resets_manual_winding_without_interpolating_toward_next_value() -> None:
    result = camera_result(
        {"tilt": [[0, 0], [240, 36], [480, "zero"], [720, 37], [960, "normal"]]},
        ConversionOptions(strict=True),
    )
    ramp, manual_hold, zero, resumed = spans(result, ControllerName.TILT)
    assert ramp.end_value == manual_hold.start_value == 36 * MANUAL_TILT_SCALE
    assert zero.start_value == zero.end_value == 0
    assert resumed.start_value == resumed.end_value == pytest.approx(MANUAL_TILT_SCALE)
