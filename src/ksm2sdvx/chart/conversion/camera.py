"""Camera graph conversion and stable laser slam association."""

from dataclasses import dataclass, replace
from itertools import pairwise

from ksm2sdvx.chart.conversion.lasers import LaserSample
from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.conversion.profiles import VoxProfile
from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline, ticks
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.geometry.curves import anchors
from ksm2sdvx.chart.kson.model import AutoTilt, CameraInfo, GraphPoint, SpinEvent, SpinKind
from ksm2sdvx.chart.vox.model import (
    AirScale,
    Controller,
    ControllerName,
    ControllerSpan,
    Realize,
    RollType,
    TiltMode,
    TiltNode,
    VoxTiltMode,
)
from ksm2sdvx.common.diagnostics import FeatureStatus


def attach_spins(
    samples: tuple[LaserSample, ...], events: tuple[SpinEvent, ...], report: ReportBuilder
) -> tuple[tuple[LaserSample, ...], int]:
    targets: list[tuple[int, int, int]] = []
    for i, (before, after) in enumerate(pairwise(samples)):
        if (before.track, before.section, before.pulse) == (
            after.track,
            after.section,
            after.pulse,
        ):
            delta = round(after.event.value, 6) - round(before.event.value, 6)
            if delta:
                targets.append((i, before.pulse, 1 if delta > 0 else -1))
    updated = list(samples)
    assigned: set[int] = set()
    end = 0
    for event in events:
        ticks(event.pulse)
        ticks(event.duration)
        if event.duration <= 0 or event.duration % 60:
            raise ConversionError(
                f"{event.path}: spin duration must be a positive multiple of 60 pulses "
                "for the VOX duration mapping; it cannot be rounded"
            )
        available = [
            (i, direction)
            for i, pulse, direction in targets
            if pulse == event.pulse and i not in assigned
        ]
        matches = [i for i, direction in available if direction == event.direction]
        if not matches:
            if len(available) == 1:
                matches = [available[0][0]]
                report.count("spin_direction_mismatches")
                report.record(
                    "spin",
                    FeatureStatus.APPROXIMATED,
                    event.path,
                    code="SPIN_DIRECTION_FALLBACK",
                    message="VOX follows the only laser slam's direction.",
                    pulse=event.pulse,
                )
            else:
                report.count("spin_events_unmapped")
                report.record(
                    "spin",
                    FeatureStatus.UNSUPPORTED,
                    event.path,
                    code="UNMATCHED_SPIN",
                    message="No unique matching laser slam.",
                    pulse=event.pulse,
                )
                continue
        if len(matches) > 1:
            report.count("spin_events_ambiguous")
            report.record(
                "spin",
                FeatureStatus.APPROXIMATED,
                event.path,
                code="AMBIGUOUS_SPIN",
                message="Selected the first slam in stable left-to-right order.",
                pulse=event.pulse,
            )
        length = event.duration
        if event.kind == SpinKind.SPIN:
            roll_type, roll_length = (
                (RollType.ROLL, length // 120)
                if length % 120 == 0
                else (RollType.ROLL_TENTHS, length // 12)
            )
        else:
            roll_type, roll_length = (
                (RollType.SWING, length // 120)
                if length % 120 == 0
                else (RollType.SWING_TENTHS, length // 12)
            )
        index = matches[0]
        sample = updated[index]
        updated[index] = replace(
            sample, event=replace(sample.event, roll_type=roll_type, roll_length=roll_length)
        )
        assigned.add(index)
        report.count(f"{event.kind.value}_events")
        report.record(
            "spin",
            FeatureStatus.APPROXIMATED,
            event.path,
            code="SPIN_DURATION_MAPPING",
            message=(
                "VOX total roll/swing duration is set to twice the source duration; "
                "the motion shapes differ. Long single spins remain single rolls."
            ),
            pulse=event.pulse,
        )
        end = max(end, event.pulse + length * 2)
    return tuple(updated), end


@dataclass(frozen=True, slots=True)
class Span:
    pulse: int
    duration: int
    start: float
    end: float
    ending_auto: bool = False


def graph_spans(points: tuple[GraphPoint, ...], step: int) -> tuple[Span, ...]:
    rows = [Span(p.pulse, 0, p.incoming, p.outgoing) for p in points if p.incoming != p.outgoing]
    for current, following in pairwise(points):
        samples = anchors(
            current.pulse,
            following.pulse,
            current.outgoing,
            following.incoming,
            current.control,
            step,
        )
        rows.extend(Span(y0, y1 - y0, v0, v1) for (y0, v0), (y1, v1) in pairwise(samples))
    return tuple(sorted(rows, key=lambda row: (row.pulse, 0 if row.duration == 0 else 1)))


def convert_camera(
    camera: CameraInfo,
    timeline: Timeline,
    options: ConversionOptions,
    profile: VoxProfile,
    report: ReportBuilder,
) -> tuple[tuple[Controller, ...], tuple[VoxTiltMode, ...], int]:
    start = timeline.position(0)
    controllers: list[tuple[int, int, Controller]] = [
        (0, 0, Realize(start, 3, *profile.radius_anchors)),
        (0, 1, Realize(start, 4, *profile.rotation_anchors)),
        (0, 2, AirScale(start, False, 1, 0, 0, 1, 0, 0)),
        (0, 3, AirScale(start, True, 1, 0, 0, 2, 0, 0)),
    ]
    report.count("camera_realize_rows", 2)
    report.count("air_scale_rows", 2)
    end = 0

    def add(span: Span, name: ControllerName, scale: float, node: int = 0) -> None:
        nonlocal end
        row = ControllerSpan(
            timeline.position(span.pulse),
            name,
            ticks(span.duration),
            span.start * scale,
            span.end * scale,
            TiltNode(node),
        )
        controllers.append((span.pulse, len(controllers), row))
        end = max(end, span.pulse + span.duration)

    for name, points, controller, scale in (
        ("zoom_bottom", camera.zoom_bottom, ControllerName.RADIUS, options.zoom_bottom_scale),
        ("zoom_top", camera.zoom_top, ControllerName.ROTATION_X, options.zoom_top_scale),
    ):
        path = f"/camera/cam/body/{name}"
        for point in points:
            timeline.position(point.pulse)
            end = max(end, point.pulse)
        rows = graph_spans(points, options.curve_step)
        for row in rows:
            add(row, controller, scale)
        report.count("camera_rows", len(rows))
        report.count(f"{name}_points", len(points))
        if len(points) == 1 and not rows and points[0].incoming != 0:
            report.record(
                name,
                FeatureStatus.UNSUPPORTED,
                path + "/0",
                code="ISOLATED_CAMERA_VALUE",
                message="Isolated nonzero camera values are not converted.",
                pulse=points[0].pulse,
            )
        if points:
            report.record(
                name,
                FeatureStatus.APPROXIMATED,
                path,
                code="CAMERA_SCALE_MAPPING",
                message="Camera values use the configured scale and are emitted as linear VOX spans.",
            )
            if any(p.control.curved for p in points[:-1]):
                report.record(
                    name,
                    FeatureStatus.APPROXIMATED,
                    path,
                    code="SAMPLED_CAMERA_CURVE",
                    message=f"Curved camera spans sampled every {options.curve_step} pulses.",
                )

    supported_modes = {AutoTilt.NORMAL: 0, AutoTilt.BIGGER: 1, AutoTilt.KEEP_BIGGER: 2}
    modes: list[tuple[int, int]] = []
    for i, point in enumerate(camera.tilt):
        timeline.position(point.pulse)
        end = max(end, point.pulse)
        for value in dict.fromkeys((point.incoming, point.outgoing)):
            if isinstance(value, AutoTilt):
                if value in supported_modes:
                    modes.append((point.pulse, supported_modes[value]))
                else:
                    report.record(
                        "tilt_mode",
                        FeatureStatus.UNSUPPORTED,
                        f"/camera/tilt/{i}",
                        code="UNSUPPORTED_TILT_MODE",
                        message=f"Automatic tilt mode {value.value!r} is not mapped.",
                        pulse=point.pulse,
                    )
        if (
            not isinstance(point.incoming, AutoTilt)
            and not isinstance(point.outgoing, AutoTilt)
            and point.incoming != point.outgoing
        ):
            add(
                Span(point.pulse, 0, point.incoming, point.outgoing),
                ControllerName.TILT,
                options.tilt_scale,
            )
            report.count("manual_tilt_rows")
    runs: list[list[Span]] = []
    manual: list[Span] | None = None
    covered: set[int] = set()
    for i, (current, following) in enumerate(pairwise(camera.tilt)):
        if isinstance(current.outgoing, AutoTilt) or isinstance(following.incoming, AutoTilt):
            manual = None
            continue
        if manual is None:
            manual = []
            runs.append(manual)
        covered.update((i, i + 1))
        samples = anchors(
            current.pulse,
            following.pulse,
            current.outgoing,
            following.incoming,
            current.control,
            options.curve_step,
        )
        for j, ((y0, v0), (y1, v1)) in enumerate(pairwise(samples)):
            manual.append(
                Span(
                    y0,
                    y1 - y0,
                    v0,
                    v1,
                    isinstance(following.outgoing, AutoTilt) and j == len(samples) - 2,
                )
            )
    for run in runs:
        for i, span in enumerate(run):
            if len(run) == 1:
                node = 1 if span.ending_auto else 2
            else:
                node = 2 if i == 0 else 3 if span.ending_auto or i == len(run) - 1 else 0
            add(span, ControllerName.TILT, options.tilt_scale, node)
            report.count("manual_tilt_rows")
    for i, point in enumerate(camera.tilt):
        if (
            i not in covered
            and not isinstance(point.incoming, AutoTilt)
            and point.incoming == point.outgoing
            and point.incoming != 0
        ):
            report.record(
                "manual_tilt",
                FeatureStatus.UNSUPPORTED,
                f"/camera/tilt/{i}",
                code="ISOLATED_TILT_VALUE",
                message="Isolated manual tilt values are not converted.",
                pulse=point.pulse,
            )
    if any(not isinstance(point.incoming, AutoTilt) for point in camera.tilt):
        report.record(
            "manual_tilt",
            FeatureStatus.APPROXIMATED,
            "/camera/tilt",
            code="TILT_SCALE_MAPPING",
            message="Manual tilt values use the configured tilt scale.",
        )
        if any(point.control.curved for point in camera.tilt[:-1]):
            report.record(
                "manual_tilt_curve",
                FeatureStatus.APPROXIMATED,
                "/camera/tilt",
                code="SAMPLED_TILT_CURVE",
                message=f"Manual tilt curves sampled every {options.curve_step} pulses.",
            )
    modes.sort(key=lambda row: row[0])
    if not modes or modes[0][0] != 0:
        modes.insert(0, (0, 0))
    report.count("auto_tilt_events", len(modes))
    for field in camera.unsupported:
        report.record(
            "camera",
            FeatureStatus.UNSUPPORTED,
            field.path,
            code="UNSUPPORTED_CAMERA",
            message="This camera feature is not converted.",
        )
    controllers.sort(key=lambda row: (row[0], row[1]))
    return (
        tuple(row[2] for row in controllers),
        tuple(VoxTiltMode(timeline.position(p), TiltMode(mode)) for p, mode in modes),
        end,
    )
