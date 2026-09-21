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
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan, VoxPosition
from ksm2sdvx.chart.vox.validation import Positions
from ksm2sdvx.common.diagnostics import FeatureStatus


def convert(beat: object, **overrides: object) -> ConversionResult:
    return convert_chart(
        parse_kson(document(beat=beat, **overrides)).chart,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
    )


def bpm_rows(result: ConversionResult) -> list[tuple[int, float, bool]]:
    positions = Positions(result.chart.meters)
    return [
        (int(positions.absolute(row.position)) * 5, row.bpm, row.pause) for row in result.chart.bpms
    ]


def test_stop_uses_native_pause_and_extends_chart() -> None:
    result = convert({"bpm": [[0, 120]], "stop": [[240, 480]]})
    assert bpm_rows(result) == [(0, 120, False), (240, 120, True), (720, 120, False)]
    assert result.report.end_pulse == 720
    assert result.report.counts["stop_intervals"] == 1
    assert next(f for f in result.report.features if f.feature == "stop").status == (
        FeatureStatus.CONVERTED
    )
    text = serialize_vox(result.chart)
    assert "001,02,00\t120.0000\t4-\n001,04,00\t120.0000\t4\n" in text


def test_overlapping_nested_and_touching_stops_form_continuous_ranges() -> None:
    result = convert({"bpm": [[0, 120]], "stop": [[120, 480], [240, 120], [600, 120], [960, 120]]})
    assert bpm_rows(result) == [
        (0, 120, False),
        (120, 120, True),
        (720, 120, False),
        (960, 120, True),
        (1080, 120, False),
    ]
    assert result.report.counts["stop_intervals"] == 2


def test_bpm_changes_at_and_inside_stop_keep_pause_state() -> None:
    result = convert({"bpm": [[0, 120], [240, 180], [480, 240], [720, 150]], "stop": [[240, 480]]})
    assert bpm_rows(result) == [
        (0, 120, False),
        (240, 180, True),
        (480, 240, True),
        (720, 150, False),
    ]


def test_pause_end_keeps_bpm_changed_during_stop() -> None:
    result = convert({"bpm": [[0, 120], [480, 240]], "stop": [[240, 480]]})
    assert bpm_rows(result)[-1] == (720, 240, False)


def test_stop_at_start_also_extends_zero_tilt_hold() -> None:
    result = convert({"bpm": [[0, 120]], "stop": [[0, 240]]}, camera={"tilt": [[0, "zero"]]})
    assert bpm_rows(result) == [(0, 120, True), (240, 120, False)]
    hold = next(
        row
        for row in result.chart.controllers
        if isinstance(row, ControllerSpan) and row.name == ControllerName.TILT
    )
    assert hold.duration == 48
    assert hold.start_value == hold.end_value == 0


def test_stop_across_meter_change_keeps_note_positions() -> None:
    beat = {"bpm": [[0, 120]], "time_sig": [[0, [4, 4]], [1, [3, 8]]]}
    note = {"bt": [[1020], [], [], []], "laser": [[[900, [[0, 0], [300, 1]]]], []]}
    baseline = convert(beat, note=note)
    result = convert({**beat, "stop": [[900, 300]]}, note=note)
    assert result.chart.tracks == baseline.chart.tracks
    assert result.chart.bpms[-1].position == VoxPosition(2, 3, VoxTick(0))
    assert bpm_rows(result) == [(0, 120, False), (900, 120, True), (1200, 120, False)]


@pytest.mark.parametrize("speed", [[[0, 2]], [[0, 1], [60, -1]], [[0, 1, [0.5, 0]], [60, 2]]])
def test_pause_does_not_overwrite_scroll_speed_updates(speed: object) -> None:
    baseline = convert({"bpm": [[0, 120]], "scroll_speed": speed})
    result = convert({"bpm": [[0, 120]], "scroll_speed": speed, "stop": [[20, 20]]})
    assert result.chart.controllers == baseline.chart.controllers
    assert bpm_rows(result) == [(0, 120, False), (20, 120, True), (40, 120, False)]


def test_zero_duration_stop_is_noop() -> None:
    baseline = convert({"bpm": [[0, 120]]})
    result = convert({"bpm": [[0, 120]], "stop": [[6, 0]]})
    assert result.chart == baseline.chart
    assert result.report.end_pulse == 0
    assert result.report.counts["stop_intervals"] == 0


@pytest.mark.parametrize("stops", [[[6, 10]], [[5, 6]], [[0, 60], [6, 5]]])
def test_nonzero_stop_boundaries_must_fit_target_grid(stops: object) -> None:
    with pytest.raises(ConversionError, match="five-pulse grid"):
        convert({"bpm": [[0, 120]], "stop": stops})
