from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    parse_kson,
    serialize_vox,
)
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.geometry.curves import curve
from ksm2sdvx.chart.kson.model import LaserSection, MeterEvent, NoteInfo, RelativeGraphPoint
from ksm2sdvx.chart.types import KsonDuration, KsonPulse, MeasureIndex


@given(
    st.floats(min_value=0, max_value=1),
    st.floats(min_value=0, max_value=1),
    st.floats(min_value=0, max_value=1),
)
def test_curve_endpoints_and_range(a: float, b: float, x: float) -> None:
    assert curve(0, a, b) == 0
    assert curve(1, a, b) == 1
    assert 0 <= curve(x, a, b) <= 1 + 1e-15
    assert curve(x, a, a) == pytest.approx(x, abs=1e-12)


@given(st.lists(st.integers(min_value=0, max_value=100000), min_size=2, unique=True))
def test_timeline_is_monotonic(tick_numbers: list[int]) -> None:
    timeline = Timeline((MeterEvent(MeasureIndex(0), 4, 4), MeterEvent(MeasureIndex(4), 7, 8)))
    positions = [timeline.position(t * 5) for t in sorted(tick_numbers)]
    assert positions == sorted(set(positions))


@given(
    st.integers(min_value=0, max_value=1000),
    st.floats(min_value=0, max_value=0.4),
    st.floats(min_value=0.6, max_value=1),
)
def test_jump_preservation_and_determinism(tick: int, before: float, after: float) -> None:
    base = parse_kson(document()).chart
    section = LaserSection(
        KsonPulse(tick * 5), (RelativeGraphPoint(KsonDuration(0), before, after),)
    )
    chart = replace(base, note=NoteInfo(laser=((section,), ())))
    first = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    second = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    assert len(first.chart.original_left) == 2
    assert [p.value for p in first.chart.original_left] == [before, after]
    assert first.chart.original_left[0].position == first.chart.original_left[1].position
    assert serialize_vox(first.chart) == serialize_vox(second.chart)
