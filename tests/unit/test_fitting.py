import pytest

from ksm2sdvx.chart.geometry.fitting import (
    FitPoint,
    fit_span,
    simplify,
    smooth_sharp_runs,
    span_error,
)
from ksm2sdvx.chart.kson.model import CurveControl


def test_compression_preserves_jump_extrema_and_plateau() -> None:
    points = (
        FitPoint(0, 0, 0),
        FitPoint(60, 0.2, 0.2),
        FitPoint(120, 0.4, 0.6),
        FitPoint(180, 0.8, 0.8),
        FitPoint(240, 1, 1),
        FitPoint(300, 1, 1),
        FitPoint(360, 0, 0),
    )
    compressed, error = simplify(points, 0.001)
    assert points[2] in compressed and points[4] in compressed and points[5] in compressed
    assert error <= 0.001
    assert simplify(points, 0)[0] == points


def test_fit_and_interior_error() -> None:
    points = (FitPoint(0, 0, 0), FitPoint(120, 0.2, 0.2), FitPoint(240, 1, 1))
    control = fit_span(points)
    assert 0 <= control.x <= 1 and 0 <= control.y <= 1
    assert span_error(points, CurveControl(0.5, 0.5)) == pytest.approx(0.3)
    assert span_error(points, control) < 0.3


def test_sharp_join_fitting() -> None:
    points = (FitPoint(0, 0, 0, CurveControl(0, 1)), FitPoint(120, 0.5, 0.5), FitPoint(240, 1, 1))
    fitted, error, changed = smooth_sharp_runs(points)
    assert changed == 1 and error <= 0.01
    assert fitted[0].control is not None and fitted[0].control.curved
    assert fitted[-1] == points[-1]


def test_invalid_fitting_inputs() -> None:
    with pytest.raises(ValueError):
        simplify((), -1)
    with pytest.raises(ValueError):
        fit_span((FitPoint(0, 0, 0), FitPoint(0, 1, 1)))
