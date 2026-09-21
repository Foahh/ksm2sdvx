from dataclasses import replace
from math import nan
from typing import Literal

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
from ksm2sdvx.chart.errors import ConversionError, KsonValidationError
from ksm2sdvx.chart.kson.model import GraphPoint
from ksm2sdvx.chart.types import KsonPulse, VoxTick
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, TiltNode, VoxChart, VoxPosition
from ksm2sdvx.common.diagnostics import FeatureStatus

type BodyName = Literal["center_split", "rotation_deg"]

START = VoxPosition(1, 1, VoxTick(0))


def convert_body(body: object, **source: object) -> ConversionResult:
    return convert_chart(
        parse_kson(document(camera={"cam": {"body": body}}, **source)).chart,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
    )


def rows(result: ConversionResult, name: ControllerName) -> list[ControllerSpan]:
    return [e for e in result.chart.controllers if isinstance(e, ControllerSpan) and e.name == name]


def test_body_fields_are_typed_and_preserve_graph_nodes() -> None:
    camera = parse_kson(
        document(
            camera={
                "cam": {
                    "body": {
                        "rotation_deg": [[0, [-90, 720], [0.2, 0.8]], [240, 0]],
                        "center_split": [[0, [0, -200]], [240, 400]],
                    }
                }
            }
        )
    ).chart.camera
    assert camera.rotation_deg[0].incoming == -90
    assert camera.rotation_deg[0].outgoing == 720
    assert camera.rotation_deg[0].control.curved
    assert camera.center_split[0].outgoing == -200
    assert camera.center_split[1].incoming == 400
    assert not camera.unsupported


@pytest.mark.parametrize("feature", ["center_split", "rotation_deg"])
@pytest.mark.parametrize("points", [[[0, True]], [[0, 1], [0, 2]], [[0, 1, [2, 0]]]])
def test_body_source_validation(feature: BodyName, points: object) -> None:
    with pytest.raises(KsonValidationError, match=feature):
        convert_body({feature: points})


@pytest.mark.parametrize("feature", ["center_split", "rotation_deg"])
def test_body_validation_applies_to_direct_models(feature: BodyName) -> None:
    chart = parse_kson(document()).chart
    graph = (GraphPoint(KsonPulse(0), nan, 0),)
    camera = (
        replace(chart.camera, center_split=graph)
        if feature == "center_split"
        else replace(chart.camera, rotation_deg=graph)
    )
    with pytest.raises(KsonValidationError, match=feature):
        convert_chart(
            replace(chart, camera=camera), options=ConversionOptions(), profile=DEFAULT_PROFILE
        )


@pytest.mark.parametrize(
    "value,expected", [(-400, -2.848), (-100, -0.712), (0, 0), (100, 0.712), (500, 3.56)]
)
def test_split_signed_values_are_not_clamped(value: float, expected: float) -> None:
    result = convert_body({"center_split": [[0, value]]})
    split = rows(result, ControllerName.MORPHING_2)
    assert len(split) == 1
    assert split[0].start_value == split[0].end_value == pytest.approx(expected)
    assert split[0].duration == 0
    assert "\tMorphing2\t2\t0\t" in serialize_vox(result.chart)


@pytest.mark.parametrize(
    "feature,name,value",
    [
        ("center_split", ControllerName.MORPHING_2, 100),
        ("rotation_deg", ControllerName.ROTATION_Z, 90),
    ],
)
def test_delayed_graph_applies_incoming_before_first_point_and_resets(
    feature: BodyName, name: ControllerName, value: float
) -> None:
    result = convert_body({feature: [[240, [value, -value]], [480, [-value, 0]]]})
    spans = rows(result, name)
    assert spans[0].position == START
    assert spans[0].start_value > 0
    jump = next(e for e in spans if e.position == VoxPosition(1, 2, VoxTick(0)))
    assert jump.duration == 0 and jump.start_value == jump.end_value < 0
    assert spans[-1].position == VoxPosition(1, 3, VoxTick(0))
    assert spans[-1].duration == 0 and spans[-1].start_value == spans[-1].end_value == 0
    assert result.report.end_pulse == 1635


def test_rotation_jumps_and_continuous_turns_use_degrees_without_wrapping() -> None:
    result = convert_body({"rotation_deg": [[0, [0, 360]], [240, 1080], [480, [1080, -360]]]})
    rotation = rows(result, ControllerName.ROTATION_Z)
    assert [(e.duration, e.start_value, e.end_value) for e in rotation] == [
        (0, 360, 360),
        (48, 360, 1080),
        (48, 1080, 1080),
        (0, -360, -360),
    ]
    assert not rows(result, ControllerName.TILT)
    text = serialize_vox(result.chart)
    assert "BIL_RotZ\t2\t0\td360.00\td360.00\t0\t" in text
    assert "BIL_RotZ\t2\t48\td360.00\td1080.00\t0\t" in text
    assert "BIL_RotZ\t2\t0\td-360.00\td-360.00\t0\t" in text


@pytest.mark.parametrize(
    "feature,name",
    [
        ("center_split", ControllerName.MORPHING_2),
        ("rotation_deg", ControllerName.ROTATION_Z),
    ],
)
def test_curves_are_sampled_including_bpm_boundaries(
    feature: BodyName, name: ControllerName
) -> None:
    result = convert_body(
        {feature: [[0, 0, [0.5, 0]], [60, 100]]},
        beat={"bpm": [[0, 120], [20, 240]]},
    )
    spans = rows(result, name)
    assert [int(e.position.tick) * 5 for e in spans] == [0, 15, 20, 30, 45]
    scale = 0.00712 if feature == "center_split" else 1.0
    # With x(t)=t and y(t)=t^2, the quarter-time value is 1/16 of the range.
    assert spans[0].end_value == pytest.approx(6.25 * scale)
    assert spans[1].end_value == pytest.approx(100 / 9 * scale)
    assert spans[-1].end_value == pytest.approx(100 * scale)


def test_linear_rotation_splits_at_bpm_change_to_preserve_pulse_interpolation() -> None:
    result = convert_body(
        {"rotation_deg": [[0, 0], [480, 360]]},
        beat={"bpm": [[0, 120], [240, 240]]},
    )
    rotation = rows(result, ControllerName.ROTATION_Z)
    assert [(e.position.beat, e.duration, e.start_value, e.end_value) for e in rotation] == [
        (1, 48, 0, 180),
        (2, 48, 180, 360),
    ]


def test_body_controls_combine_with_zoom_and_extend_zero_tilt_hold() -> None:
    result = convert_chart(
        parse_kson(
            document(
                camera={
                    "tilt": [[0, 0]],
                    "cam": {
                        "body": {
                            "zoom_bottom": [[0, 50]],
                            "center_split": [[0, 0], [480, 200]],
                            "rotation_deg": [[0, -90], [960, 720]],
                        }
                    },
                }
            )
        ).chart,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
    )
    assert result.report.end_pulse == 2115
    assert result.chart.end_position == VoxPosition(3, 1, VoxTick(39))
    (hold,) = rows(result, ControllerName.TILT)
    assert hold.duration == 423 and hold.node_type == TiltNode.SINGLE
    assert hold.start_value == hold.end_value == 0
    assert rows(result, ControllerName.RADIUS)
    assert rows(result, ControllerName.ROTATION_X)
    assert rows(result, ControllerName.MORPHING_2)[-1].end_value == pytest.approx(1.424)
    assert rows(result, ControllerName.ROTATION_Z)[-1].end_value == 720
    assert [c.position for c in result.chart.controllers] == sorted(
        c.position for c in result.chart.controllers
    )
    assert all(
        f.status == FeatureStatus.APPROXIMATED
        for f in result.report.features
        if f.feature in ("center_split", "rotation_deg")
    )
    serialize_vox(result.chart)


@pytest.mark.parametrize("feature", ["center_split", "rotation_deg"])
def test_empty_graph_does_not_emit_rows_or_diagnostic(feature: BodyName) -> None:
    result = convert_body({feature: []})
    assert len(result.chart.controllers) == 4
    assert all(f.feature != feature for f in result.report.features)


@pytest.mark.parametrize("feature", ["center_split", "rotation_deg"])
def test_body_values_outside_target_range_are_rejected(feature: BodyName) -> None:
    with pytest.raises(ConversionError, match="float32"):
        convert_body({feature: [[0, 1e300]]})


@pytest.mark.parametrize("feature", ["center_split", "rotation_deg"])
def test_body_source_anchors_must_fit_target_grid(feature: BodyName) -> None:
    with pytest.raises(ConversionError, match="five-pulse"):
        convert_body({feature: [[0, 0], [241, 0]]})


@pytest.mark.parametrize("name", [ControllerName.MORPHING_2, ControllerName.ROTATION_Z])
def test_target_span_rejects_overflowing_endpoint_delta(
    vox_chart: VoxChart, name: ControllerName
) -> None:
    span = ControllerSpan(START, name, VoxTick(48), -3e38, 3e38)
    with pytest.raises(ConversionError, match="float32"):
        serialize_vox(replace(vox_chart, controllers=(span,)))


def test_rotation_target_duration_is_validated(vox_chart: VoxChart) -> None:
    span = ControllerSpan(START, ControllerName.ROTATION_Z, VoxTick(1_000_000), 0, 90)
    with pytest.raises(ConversionError, match="duration exceeds"):
        serialize_vox(replace(vox_chart, controllers=(span,)))
