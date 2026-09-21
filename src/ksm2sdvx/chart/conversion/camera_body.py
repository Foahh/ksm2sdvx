"""Linear controller mappings for camera body graphs."""

from bisect import bisect_left, bisect_right
from itertools import pairwise

from ksm2sdvx.chart.conversion.timing import Timeline, ticks
from ksm2sdvx.chart.geometry.curves import curve
from ksm2sdvx.chart.kson.model import GraphPoint
from ksm2sdvx.chart.vox.model import ControllerName, ControllerSpan

CENTER_SPLIT_SCALE = 0.00712  # 100 source units add one BT lane's width.


def body_graph(
    points: tuple[GraphPoint, ...],
    timeline: Timeline,
    step: int,
    bpm_pulses: tuple[int, ...],
    name: ControllerName,
    scale: float,
) -> tuple[ControllerSpan, ...]:
    rows: list[ControllerSpan] = []
    for point in points:
        timeline.position(point.pulse)

    def add(start: int, stop: int, first: float, last: float) -> None:
        rows.append(
            ControllerSpan(
                timeline.position(start), name, ticks(stop - start), first * scale, last * scale
            )
        )

    if points and points[0].pulse > 0:
        add(0, 0, points[0].incoming, points[0].incoming)
    for i, point in enumerate(points):
        if point.incoming != point.outgoing or len(points) == 1:
            # Equal endpoints apply the outgoing value even at the exact jump time.
            add(point.pulse, point.pulse, point.outgoing, point.outgoing)
        if i + 1 == len(points):
            continue
        following = points[i + 1]
        times: set[int] = {point.pulse, following.pulse}
        times.update(
            bpm_pulses[
                bisect_right(bpm_pulses, point.pulse) : bisect_left(bpm_pulses, following.pulse)
            ]
        )
        if point.control.curved:
            times.update(range(point.pulse + step, following.pulse, step))
        samples: list[tuple[int, float]] = []
        for pulse in sorted(times):
            amount = (pulse - point.pulse) / (following.pulse - point.pulse)
            if point.control.curved:
                amount = curve(amount, point.control.x, point.control.y)
            value = (1 - amount) * point.outgoing + amount * following.incoming
            samples.append((pulse, value))
        for (start, first), (stop, last) in pairwise(samples):
            add(start, stop, first, last)
    return tuple(rows)
