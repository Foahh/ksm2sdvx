import math

import pytest
from tests.conftest import document

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions, convert_chart, parse_kson
from ksm2sdvx.chart.conversion.converter import ConversionResult
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, Realize


def camera_result(camera: object, options: ConversionOptions | None = None) -> ConversionResult:
    return convert_chart(
        parse_kson(document(camera=camera)).chart,
        options=options or ConversionOptions(),
        profile=DEFAULT_PROFILE,
    )


def test_realize_precedes_pulse_zero_camera_jumps() -> None:
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
    controls = result.chart.controllers
    assert isinstance(controls[0], Realize) and controls[0].controller == 3
    assert isinstance(controls[1], Realize) and controls[1].controller == 4
    assert (controls[0].c4, controls[0].c5, controls[0].c6) == (17.12, 60.12, 110.12)
    jumps = {
        c.name: c.end_value for c in controls if isinstance(c, ControllerSpan) and c.duration == 0
    }
    assert jumps[ControllerName.RADIUS] == pytest.approx(-0.382)
    assert jumps[ControllerName.ROTATION_X] == pytest.approx(0.13225)


def test_radius_scale_output() -> None:
    result = camera_result(
        {
            "cam": {
                "body": {"zoom_bottom": [[240 * i, v] for i, v in enumerate((0, 25, 50, 75, 100))]}
            }
        }
    )
    outputs = [0.0] + [
        c.end_value for c in result.chart.controllers if isinstance(c, ControllerSpan)
    ]
    assert outputs == pytest.approx([0.0, -0.0955, -0.191, -0.2865, -0.382])


def test_default_camera_initialization() -> None:
    result = camera_result({})
    initializers = [c for c in result.chart.controllers if isinstance(c, Realize)]
    assert [(c.controller, c.c4, c.c5, c.c6) for c in initializers] == [
        (3, 17.12, 60.12, 110.12),
        (4, 0.28, 0.72, 1.57),
    ]


def test_independent_scales_cover_jumps() -> None:
    result = camera_result(
        {
            "cam": {
                "body": {
                    "zoom_top": [[0, [25, 50]], [240, 100]],
                    "zoom_bottom": [[0, [25, 50]], [240, 100]],
                }
            },
            "tilt": [[0, [0.25, 0.5]], [240, 1], [480, [1, "normal"]]],
        },
        ConversionOptions(zoom_top_scale=0.02, zoom_bottom_scale=-0.04, tilt_scale=-0.4),
    )
    jumps = {
        c.name: (c.start_value, c.end_value)
        for c in result.chart.controllers
        if isinstance(c, ControllerSpan) and c.duration == 0
    }
    assert jumps == {
        ControllerName.ROTATION_X: (0.5, 1.0),
        ControllerName.RADIUS: (-1.0, -2.0),
        ControllerName.TILT: (-0.1, -0.2),
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_invalid_scales_are_rejected(value: float) -> None:
    for options in (
        ConversionOptions(zoom_top_scale=value),
        ConversionOptions(zoom_bottom_scale=value),
        ConversionOptions(tilt_scale=value),
    ):
        with pytest.raises(ConversionError):
            camera_result({}, options)


def test_separate_manual_sequences_restart_node_encoding() -> None:
    result = camera_result({"tilt": [[0, 0], [240, [1, "normal"]], [480, 0], [720, [1, "normal"]]]})
    spans = [c for c in result.chart.controllers if isinstance(c, ControllerSpan)]
    assert [span.node_type for span in spans] == [1, 1]


def test_manual_curve_reports_sampling() -> None:
    result = camera_result({"tilt": [[0, [0, [0.2, 0.8]]], [240, 1]]})
    assert "SAMPLED_TILT_CURVE" in {d.code for d in result.report.diagnostics}
