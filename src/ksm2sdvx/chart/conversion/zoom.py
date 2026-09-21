"""Evaluate coupled zoom graphs on the target timing grid."""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise

from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.geometry.camera import (
    PROJECTION_TOLERANCE,
    CameraPose,
    Normalization,
    projection_error,
    zoom_pose,
)
from ksm2sdvx.chart.geometry.curves import curve
from ksm2sdvx.chart.kson.model import GraphPoint


@dataclass(frozen=True, slots=True)
class ZoomSpan:
    pulse: int
    duration: int
    start: CameraPose
    end: CameraPose


class ZoomGraph:
    def __init__(self, points: tuple[GraphPoint, ...]) -> None:
        self.points = points
        self.pulses = tuple(p.pulse for p in points)

    def value(self, pulse: float, *, before: bool = False) -> float:
        if not self.points:
            return 0.0
        index = bisect_right(self.pulses, pulse) - 1
        if index < 0:
            return self.points[0].incoming
        current = self.points[index]
        if before and pulse == current.pulse:
            return current.incoming
        if index == len(self.points) - 1:
            return current.outgoing
        following = self.points[index + 1]
        amount = (pulse - current.pulse) / (following.pulse - current.pulse)
        if current.control.curved:
            amount = curve(amount, current.control.x, current.control.y)
        return current.outgoing + (following.incoming - current.outgoing) * amount


def zoom_spans(
    bottom_points: tuple[GraphPoint, ...],
    top_points: tuple[GraphPoint, ...],
    radius: Normalization,
    rotation: Normalization,
    step: int,
) -> tuple[ZoomSpan, ...]:
    if not bottom_points and not top_points:
        return ()
    bottom, top = ZoomGraph(bottom_points), ZoomGraph(top_points)
    knots = sorted({0, *bottom.pulses, *top.pulses})
    rows: list[ZoomSpan] = []

    def pose(pulse: float, *, before: bool = False) -> CameraPose:
        b, t = bottom.value(pulse, before=before), top.value(pulse, before=before)
        try:
            return zoom_pose(b, t, radius, rotation)
        except ConversionError as error:
            raise ConversionError(
                f"/camera/cam/body at pulse {pulse:g} (bottom={b:g}, top={t:g}): {error}"
            ) from error

    def subdivide(lo: int, hi: int, first: CameraPose, last: CameraPose) -> None:
        error = max(
            projection_error(first, last, pose(lo + (hi - lo) * t), t) for t in (0.25, 0.5, 0.75)
        )
        travel = abs(top.value(hi, before=True) - top.value(lo))
        moving = bottom.value(lo) != bottom.value(hi, before=True) or top.value(lo) != top.value(
            hi, before=True
        )
        if error <= PROJECTION_TOLERANCE and travel <= 25 and (hi - lo <= step or not moving):
            rows.append(ZoomSpan(lo, hi - lo, first, last))
            return
        if hi - lo <= 5:
            raise ConversionError(
                f"Camera motion at pulse {lo} exceeds the projection tolerance on one VOX tick"
            )
        mid = lo + max(5, (hi - lo) // 10 * 5)
        middle = pose(mid)
        subdivide(lo, mid, first, middle)
        subdivide(mid, hi, middle, last)

    neutral = zoom_pose(0, 0, radius, rotation)
    for index, pulse in enumerate(knots):
        before, after = pose(pulse, before=True), pose(pulse)
        if index == 0 and before == after:
            before = neutral
        if before != after:
            rows.append(ZoomSpan(pulse, 0, before, after))
        if index == len(knots) - 1:
            continue
        stop = knots[index + 1]
        # The bottom projection changes slope at zero, including inside curves.
        cuts = {pulse, stop}
        start_value, end_value = bottom.value(pulse), bottom.value(stop, before=True)
        if start_value * end_value < 0:
            low, high = float(pulse), float(stop)
            for _ in range(48):
                middle = (low + high) / 2
                if (bottom.value(middle) > 0) == (start_value > 0):
                    low = middle
                else:
                    high = middle
            tick = round((low + high) / 10)
            cuts.update(p for p in (tick * 5 - 5, tick * 5, tick * 5 + 5) if pulse < p < stop)
        for lo, hi in pairwise(sorted(cuts)):
            subdivide(lo, hi, pose(lo), pose(hi, before=True))
    return tuple(rows)
