"""Convert scroll-speed graphs to instantaneous VOX multiplier updates."""

from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.geometry.curves import curve
from ksm2sdvx.chart.kson.model import GraphPoint
from ksm2sdvx.chart.vox.model import ManualSpeed
from ksm2sdvx.common.diagnostics import FeatureStatus


def convert_scroll_speed(
    points: tuple[GraphPoint, ...], timeline: Timeline, step: int, report: ReportBuilder
) -> tuple[tuple[ManualSpeed, ...], int]:
    path = "/beat/scroll_speed"
    report.count("scroll_speed_points", len(points))
    for point in points:
        timeline.position(point.pulse)

    rows: list[ManualSpeed] = []
    previous = 1.0

    def add(pulse: int, value: float) -> None:
        nonlocal previous
        if value != previous:
            rows.append(ManualSpeed(timeline.position(pulse), value))
            previous = value

    if points and points[0].pulse > 0:
        add(0, points[0].incoming)
    sampled = False
    for i, point in enumerate(points):
        # At an anchor the outgoing value wins; the incoming value ends the prior ramp.
        add(point.pulse, point.outgoing)
        if i + 1 == len(points):
            continue
        following = points[i + 1]
        if point.outgoing == following.incoming:
            continue
        sampled = True
        for pulse in range(point.pulse + step, following.pulse, step):
            amount = (pulse - point.pulse) / (following.pulse - point.pulse)
            if point.control.curved:
                amount = curve(amount, point.control.x, point.control.y)
            add(pulse, (1 - amount) * point.outgoing + amount * following.incoming)

    report.count("scroll_speed_rows", len(rows))
    if sampled:
        report.record(
            "scroll_speed",
            FeatureStatus.APPROXIMATED,
            path,
            code="SAMPLED_SCROLL_SPEED",
            message=f"Scroll-speed ramps use instantaneous updates every {step} KSON pulses.",
        )
    else:
        report.record("scroll_speed", FeatureStatus.CONVERTED, path)
    return tuple(rows), points[-1].pulse if points else 0
