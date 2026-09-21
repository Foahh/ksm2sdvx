from dataclasses import replace
from fractions import Fraction

import pytest
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    parse_kson,
    serialize_vox,
)
from ksm2sdvx.chart.conversion.converter import UnsupportedFeaturesError
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.kson.model import MeterEvent
from ksm2sdvx.chart.types import MeasureIndex, VoxTick
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, Realize, VoxPosition
from ksm2sdvx.common.diagnostics import FeatureStatus


def test_meter_boundaries_and_unusual_denominators() -> None:
    timeline = Timeline((MeterEvent(MeasureIndex(0), 4, 4), MeterEvent(MeasureIndex(2), 3, 8)))
    assert timeline.position(1920) == VoxPosition(3, 1, VoxTick(0))
    assert timeline.position(2040) == VoxPosition(3, 2, VoxTick(0))
    assert timeline.position(2280) == VoxPosition(4, 1, VoxTick(0))
    unusual = Timeline((MeterEvent(MeasureIndex(0), 5, 7),))
    with pytest.raises(ConversionError):
        unusual.position(140)
    with pytest.raises(ConversionError):
        timeline.position(Fraction(1, 2))


@pytest.mark.parametrize(
    "overrides",
    [
        {"note": {"bt": [[1], (), (), ()]}},
        {"note": {"fx": [[[0, 6]], ()]}},
        {"note": {"laser": [[[0, [[0, 0], [6, 1]]]], ()]}},
        {"beat": {"bpm": [[0, 120], [6, 130]]}},
        {"camera": {"tilt": [[6, "normal"]]}},
        {"camera": {"cam": {"body": {"zoom_top": [[6, 1]]}}}},
    ],
)
def test_off_grid_is_always_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ConversionError):
        convert_chart(
            parse_kson(document(**overrides)).chart,
            options=ConversionOptions(),
            profile=DEFAULT_PROFILE,
        )


def test_end_includes_timing_and_modes() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120], [960, 180]], "time_sig": [[0, [4, 4]], [2, [3, 4]]]},
            camera={"tilt": [[2880, "bigger"]]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    assert result.report.end_pulse == 2880
    assert result.chart.end_position == result.chart.tilt_modes[-1].position


def test_losses_and_strict_mode() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120]], "stop": [[240, 240]], "scroll_speed": [[0, 2]]},
            camera={"tilt": [[0, "biggest"]]},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    codes = {d.code for d in result.report.diagnostics}
    assert "UNSUPPORTED_TILT_MODE" in codes
    assert "UNSUPPORTED_SCROLL_SPEED" not in codes
    assert any(f.status == FeatureStatus.UNSUPPORTED for f in result.report.features)
    with pytest.raises(UnsupportedFeaturesError) as caught:
        convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    assert caught.value.report.diagnostics


def test_deferred_metadata_and_bgm_do_not_fail_strict() -> None:
    chart = parse_kson(document(audio={"bgm": {"filename": "absent.ogg", "offset": -5}})).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    assert any(f.status == FeatureStatus.DEFERRED for f in result.report.features)


def test_spin_fallback_ambiguity_and_missing() -> None:
    laser = [0, [[0, 0], [240, [0.25, 0.75]], [480, 1]]]
    for lanes, direction, code in (
        ([[laser], ()], -1, "SPIN_DIRECTION_FALLBACK"),
        ([[laser], [laser]], 1, "AMBIGUOUS_SPIN"),
        ([(), ()], 1, "UNMATCHED_SPIN"),
    ):
        chart = parse_kson(
            document(
                note={"laser": lanes},
                camera={
                    "cam": {"pattern": {"laser": {"slam_event": {"spin": [[240, direction, 240]]}}}}
                },
            )
        ).chart
        result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
        assert code in {d.code for d in result.report.diagnostics}
        if code != "UNMATCHED_SPIN":
            assert any(p.roll_type == 1 for p in result.chart.original_left)
            assert result.chart.original_left == result.chart.tracks[0].events


def test_converter_initializes_before_values_and_serializer_preserves_order() -> None:
    chart = parse_kson(
        document(camera={"cam": {"body": {"zoom_top": [[0, [0, 100]], [240, 0]]}}})
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    controls = result.chart.controllers
    jump = next(
        c for c in controls if isinstance(c, ControllerSpan) and c.name == ControllerName.ROTATION_X
    )
    assert isinstance(controls[0], Realize)
    text = serialize_vox(replace(result.chart, controllers=(jump, *controls)))
    # File order is preserved; Realize-first is a converter choice, not a format rule.
    assert text.index("\tCAM_RotX") < text.index("\tRealize")
