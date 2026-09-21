"""Combine BPM changes and scroll-stop boundaries."""

from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.kson.model import BeatInfo
from ksm2sdvx.chart.vox.model import VoxBpmEvent
from ksm2sdvx.common.diagnostics import FeatureStatus


def convert_bpms(
    beat: BeatInfo, timeline: Timeline, report: ReportBuilder
) -> tuple[tuple[VoxBpmEvent, ...], int]:
    ranges: list[tuple[int, int]] = []
    for stop in beat.stops:
        if not stop.duration:
            continue
        start, end = stop.pulse, stop.pulse + stop.duration
        timeline.position(start)
        timeline.position(end)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
        else:
            ranges.append((start, end))

    changes: dict[int, float] = {event.pulse: event.bpm for event in beat.bpm}
    boundaries = {
        pulse: state for start, end in ranges for pulse, state in ((start, True), (end, False))
    }
    bpm = beat.bpm[0].bpm
    paused = False
    rows: list[VoxBpmEvent] = []
    pulses = sorted(changes.keys() | boundaries.keys())
    for pulse in pulses:
        bpm = changes.get(pulse, bpm)
        paused = boundaries.get(pulse, paused)
        rows.append(VoxBpmEvent(timeline.position(pulse), bpm, paused))

    report.count("stop_intervals", len(ranges))
    if beat.stops:
        report.record("stop", FeatureStatus.CONVERTED, "/beat/stop")
    return tuple(rows), pulses[-1]
