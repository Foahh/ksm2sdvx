from pathlib import Path

import pytest

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    convert_chart,
    load_kson,
    serialize_vox,
)


@pytest.mark.parametrize("name", ["minimal", "notes", "camera"])
def test_golden_output(fixture_root: Path, name: str) -> None:
    chart = load_kson(fixture_root / "kson" / f"{name}.kson").chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    actual = serialize_vox(result.chart)
    expected = (fixture_root / "vox" / f"{name}.vox").read_text(encoding="utf-8")
    assert actual == expected
    assert serialize_vox(result.chart) == actual
    assert "\r" not in actual
