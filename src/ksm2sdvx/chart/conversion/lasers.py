from dataclasses import dataclass

from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.geometry.curves import anchors
from ksm2sdvx.chart.kson.model import NoteInfo
from ksm2sdvx.chart.types import KsonPulse
from ksm2sdvx.chart.vox.model import LaserMarker, VoxLaserPoint
from ksm2sdvx.common.diagnostics import FeatureStatus


@dataclass(frozen=True, slots=True)
class LaserSample:
    pulse: KsonPulse
    track: int
    section: int
    sequence: int
    event: VoxLaserPoint
    control_node: bool


def convert_lasers(
    notes: NoteInfo, timeline: Timeline, step: int, report: ReportBuilder
) -> tuple[LaserSample, ...]:
    samples: list[LaserSample] = []
    for lane_index, lane in enumerate(notes.laser):
        track = 1 if lane_index == 0 else 8
        for section_index, section in enumerate(lane):
            emitted: list[tuple[int, float]] = []
            controls = {
                (section.pulse + point.offset, value)
                for point in section.points
                for value in (point.incoming, point.outgoing)
            }
            for i, point in enumerate(section.points):
                pulse = section.pulse + point.offset
                timeline.position(pulse)  # Validate source anchors, even if deduplicated.
                if not emitted or emitted[-1] != (pulse, point.incoming):
                    emitted.append((pulse, point.incoming))
                if point.incoming != point.outgoing:
                    emitted.append((pulse, point.outgoing))
                if i + 1 < len(section.points):
                    following = section.points[i + 1]
                    emitted.extend(
                        anchors(
                            pulse,
                            section.pulse + following.offset,
                            point.outgoing,
                            following.incoming,
                            point.control,
                            step,
                        )[1:]
                    )
                    if point.control.curved:
                        report.record(
                            "laser_curve",
                            FeatureStatus.APPROXIMATED,
                            f"/note/laser/{lane_index}/{section_index}/1/{i}",
                            code="SAMPLED_CURVE",
                            message=f"Curved laser spans sampled every {step} pulses.",
                            pulse=KsonPulse(pulse),
                        )
            if len(emitted) == 1:
                emitted.append(emitted[0])
            for i, (pulse, value) in enumerate(emitted):
                marker = (
                    LaserMarker.START
                    if i == 0
                    else LaserMarker.END
                    if i == len(emitted) - 1
                    else LaserMarker.CONTINUE
                )
                samples.append(
                    LaserSample(
                        KsonPulse(pulse),
                        track,
                        section_index,
                        len(samples),
                        VoxLaserPoint(timeline.position(pulse), value, marker, section.width),
                        (pulse, value) in controls,
                    )
                )
            report.count("laser_sections")
            report.count("wide_laser_sections", int(section.width == 2))
            report.count("laser_rows", len(emitted))
            report.count("original_laser_rows", sum(row in controls for row in emitted))
    return tuple(samples)
