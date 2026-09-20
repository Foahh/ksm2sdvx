"""Optional sample compression; deliberately independent of chart conversion."""

import math
from dataclasses import dataclass, replace
from itertools import pairwise

from ksm2sdvx.chart.geometry.curves import parameter
from ksm2sdvx.chart.kson.model import CurveControl


@dataclass(frozen=True, slots=True)
class FitPoint:
    time: int
    incoming: float
    outgoing: float
    control: CurveControl | None = None

    @property
    def jump(self) -> bool:
        return self.incoming != self.outgoing


def _validate(points: tuple[FitPoint, ...], tolerance: float = 0.0) -> None:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Tolerance must be finite and nonnegative")
    if any(not math.isfinite(v) for p in points for v in (p.time, p.incoming, p.outgoing)):
        raise ValueError("Samples must be finite")
    if any(right.time <= left.time for left, right in pairwise(points)):
        raise ValueError("Sample times must be strictly increasing")


def fit_span(points: tuple[FitPoint, ...]) -> CurveControl:
    _validate(points)
    if len(points) < 2:
        raise ValueError("Fitting needs at least two points")
    t0, t1 = points[0].time, points[-1].time
    v0, v1 = points[0].outgoing, points[-1].incoming
    dv = v1 - v0
    xy = [((p.time - t0) / (t1 - t0), (p.incoming - v0) / dv) for p in points[1:-1]] if dv else []
    if not xy:
        return CurveControl(0.5, 0.5)

    def candidate(a: float) -> tuple[float, float, float]:
        terms = [(parameter(x, a), y) for x, y in xy]
        den = sum((2 * u * (1 - u)) ** 2 for u, _ in terms)
        b = max(0.0, min(1.0, sum(2 * u * (1 - u) * (y - u * u) for u, y in terms) / den))
        return sum((2 * b * u * (1 - u) + u * u - y) ** 2 for u, y in terms), a, b

    best = min(candidate(i / 20) for i in range(21))
    step = 0.05
    for _ in range(12):
        best = min(best, candidate(max(0.0, best[1] - step)), candidate(min(1.0, best[1] + step)))
        step /= 2
    # Preserve the existing a=0.5 perturbation for curved edges.
    if best[1] == 0.5 and best[2] != 0.5:
        best = min(candidate(0.499999), candidate(0.500001))
    return CurveControl(best[1], best[2])


def span_error(points: tuple[FitPoint, ...], control: CurveControl) -> float:
    """Maximum deviation includes interior extrema of each source linear span."""
    _validate(points)
    if len(points) < 2:
        raise ValueError("Error measurement needs at least two points")
    a, b = control.x, control.y
    t0, t1 = points[0].time, points[-1].time
    v0, dv = points[0].outgoing, points[-1].incoming - points[0].outgoing
    worst = 0.0
    for left, right in pairwise(points):
        x0, x1 = (left.time - t0) / (t1 - t0), (right.time - t0) / (t1 - t0)
        y0, y1 = left.outgoing, right.incoming
        slope = (y1 - y0) / (x1 - x0)
        qa, qb = dv * (1 - 2 * b) - slope * (1 - 2 * a), 2 * dv * b - 2 * slope * a
        qc = v0 - y0 + slope * x0
        u0, u1 = parameter(x0, a), parameter(x1, a)
        probes = [u0, u1]
        if abs(qa) > 1e-15:
            root = -qb / (2 * qa)
            if u0 < root < u1:
                probes.append(root)
        worst = max(worst, *(abs(qa * u * u + qb * u + qc) for u in probes))
    return worst


def _boundaries(points: tuple[FitPoint, ...], *, preserve_controls: bool) -> list[int]:
    fixed = {0, len(points) - 1}
    for i, point in enumerate(points):
        if point.jump:
            fixed.add(i)
        if preserve_controls and point.control is not None:
            fixed.update((i, min(i + 1, len(points) - 1)))
        if 0 < i < len(points) - 1:
            incoming = point.incoming - points[i - 1].outgoing
            outgoing = points[i + 1].incoming - point.outgoing
            if incoming * outgoing < 0 or (incoming == 0) != (outgoing == 0):
                fixed.add(i)
    return sorted(fixed)


def simplify(points: tuple[FitPoint, ...], tolerance: float) -> tuple[tuple[FitPoint, ...], float]:
    _validate(points, tolerance)
    if tolerance == 0 or len(points) <= 2:
        return points, 0.0
    result: list[FitPoint] = []
    worst = 0.0
    bounds = _boundaries(points, preserve_controls=True)
    for lo, hi in pairwise(bounds):
        stack = [(lo, hi)]
        while stack:
            start, stop = stack.pop()
            if stop - start == 1:
                result.append(points[start])
                continue
            samples = points[start : stop + 1]
            control = CurveControl(0.5, 0.5)
            error = span_error(samples, control)
            if error > tolerance:
                control = fit_span(samples)
                error = span_error(samples, control)
            if error <= tolerance:
                result.append(replace(points[start], control=control if control.curved else None))
                worst = max(worst, error)
            else:
                middle = (start + stop) // 2
                stack.extend(((middle, stop), (start, middle)))
    result.append(points[-1])
    return tuple(result), worst


def smooth_sharp_runs(
    points: tuple[FitPoint, ...], tolerance: float = 0.002
) -> tuple[tuple[FitPoint, ...], float, int]:
    """Fit runs using minimum curvature and post-slam span constraints.

    The returned error can exceed tolerance: this algorithm permits 1% deviation
    and enforces a minimum 60-pulse first span after a slam where possible.
    """
    _validate(points, tolerance)
    if len(points) < 2:
        return points, 0.0, 0
    result: list[FitPoint] = []
    worst, changed = 0.0, 0
    bounds = _boundaries(points, preserve_controls=False)
    for lo, hi in pairwise(bounds):
        samples = points[lo : hi + 1]
        pointed = samples[0].control == CurveControl(0.0, 1.0) or samples[
            -2
        ].control == CurveControl(1.0, 0.0)
        sample_count = len(samples)
        post_slam = (
            samples[0].jump
            and sample_count > 2
            and span_error(samples, CurveControl(0.5, 0.5)) > 1e-5
        )
        if not (pointed or post_slam) or samples[0].outgoing == samples[-1].incoming:
            result.extend(samples[:-1])
            continue
        changed += 1
        stack = [(0, len(samples) - 1)]
        while stack:
            start, stop = stack.pop()
            span = samples[start : stop + 1]
            control = fit_span(span)
            if pointed and abs(control.x - control.y) < 0.01:
                a = 0.499999 if control.x == 0.5 else control.x
                candidates = (min(1.0, a + 0.01), max(0.0, a - 0.01))
                b = min(
                    (v for v in candidates if v != a),
                    key=lambda v: span_error(span, CurveControl(a, v)),
                )
                control = CurveControl(a, b)
            error = span_error(span, control)
            allowed = (
                max(tolerance, 0.01) if pointed or (start == 0 and samples[0].jump) else tolerance
            )
            if error <= allowed:
                result.append(replace(span[0], control=control))
                worst = max(worst, error)
            elif stop - start > 1:
                middle = (start + stop) // 2
                if start == 0 and samples[0].jump:
                    safe = next(
                        (i for i in range(1, stop + 1) if samples[i].time - samples[0].time >= 60),
                        stop,
                    )
                    middle = max(middle, safe)
                    if middle >= stop:
                        result.append(replace(span[0], control=control))
                        worst = max(worst, error)
                        continue
                stack.extend(((middle, stop), (start, middle)))
            else:
                raise ValueError("Sharp tolerance too small for stable nonzero curvature")
    result.append(points[-1])
    return tuple(result), worst, changed
