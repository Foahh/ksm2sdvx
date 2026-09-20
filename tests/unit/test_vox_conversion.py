from dataclasses import replace

import pytest
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    parse_kson,
    serialize_vox,
)
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.vox.model import RollType, VoxFxHold
from ksm2sdvx.common.diagnostics import FeatureStatus


@pytest.mark.parametrize(
    ("kind", "duration", "roll_type", "roll_length"),
    [
        ("spin", 240, RollType.ROLL, 2),
        ("spin", 960, RollType.ROLL, 8),
        ("spin", 60, RollType.ROLL_TENTHS, 5),
        ("half_spin", 240, RollType.SWING, 2),
        ("half_spin", 60, RollType.SWING_TENTHS, 5),
    ],
)
def test_spin_encoding_and_full_duration_end(
    kind: str, duration: int, roll_type: RollType, roll_length: int
) -> None:
    chart = parse_kson(
        document(
            note={"laser": [[[0, [[0, [0, 1]]]]], []]},
            camera={"cam": {"pattern": {"laser": {"slam_event": {kind: [[0, 1, duration]]}}}}},
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    point = result.chart.original_left[0]
    assert (point.roll_type, point.roll_length) == (roll_type, roll_length)
    assert result.report.end_pulse == 2 * duration
    assert any(d.code == "SPIN_DURATION_MAPPING" for d in result.report.diagnostics)
    assert any(
        f.feature == "spin" and f.status == FeatureStatus.APPROXIMATED
        for f in result.report.features
    )
    assert serialize_vox(result.chart)
    with pytest.raises(ConversionError, match="Roll duration"):
        serialize_vox(replace(result.chart, end_position=point.position))


def test_unrepresentable_spin_duration_is_not_rounded() -> None:
    chart = parse_kson(
        document(
            note={"laser": [[[0, [[0, [0, 1]]]]], []]},
            camera={"cam": {"pattern": {"laser": {"slam_event": {"spin": [[0, 1, 15]]}}}}},
        )
    ).chart
    with pytest.raises(ConversionError, match="cannot be rounded"):
        convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)


def test_original_tracks_only_contain_source_anchors_and_jumps() -> None:
    chart = parse_kson(
        document(note={"laser": [[[0, [[0, 0, [0.2, 0.8]], [240, [0.5, 0.8]], [480, 1]], 2]], []]})
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    assert len(result.chart.tracks[0].events) > 4
    original = result.chart.original_left
    assert [p.value for p in original] == [0, 0.5, 0.8, 1]
    assert all(p.width == 2 for p in original)
    assert original[1].position == original[2].position
    assert result.report.counts["original_laser_rows"] == 4


def test_fx_hold_references_explicit_no_effect_pair() -> None:
    chart = parse_kson(document(note={"fx": [[[0, 240]], []]})).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    note = result.chart.tracks[1].events[0]
    assert isinstance(note, VoxFxHold)
    assert note.effect_pair == 2
    assert result.chart.fx_effects[0].first.kind == result.chart.fx_effects[0].second.kind == 0
    assert len(result.chart.laser_effects) == 5
    assert len(result.chart.fx_effects) == 12
    assert len(result.chart.parameter_assignments) == 24
