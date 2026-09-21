"""Camera graph conversion and stable laser slam association."""

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import pairwise
from math import ceil, fmod, isfinite

from ksm2sdvx.chart.conversion.camera_body import CENTER_SPLIT_SCALE, body_graph
from ksm2sdvx.chart.conversion.lasers import LaserSample
from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.conversion.profiles import VoxProfile
from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline, ticks
from ksm2sdvx.chart.conversion.zoom import zoom_spans
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.geometry.camera import MANUAL_TILT_SCALE, Normalization
from ksm2sdvx.chart.geometry.curves import anchors
from ksm2sdvx.chart.kson.model import AutoTilt, BpmEvent, CameraInfo, SpinEvent, SpinKind, TiltEvent
from ksm2sdvx.chart.vox.model import (
    AirScale,
    Controller,
    ControllerName,
    ControllerSpan,
    Realize,
    RollType,
    TiltMode,
    TiltNode,
    VoxPosition,
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
        if event.duration == 0:
            report.count("zero_duration_spin_events")
            report.record(
                "spin",
                FeatureStatus.CONVERTED,
                event.path,
                pulse=event.pulse,
            )
            continue
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


def rebase_tilt(points: tuple[TiltEvent, ...]) -> tuple[TiltEvent, ...]:
    """Remove full turns only at discontinuities; keep continuous winding."""

    def principal(value: float) -> float:
        reduced = fmod(value, 36)
        return reduced - 36 if reduced > 18 else reduced + 36 if reduced < -18 else reduced

    offset = 0.0
    active = False
    result: list[TiltEvent] = []
    for point in points:
        incoming, outgoing = point.incoming, point.outgoing
        if isinstance(incoming, AutoTilt):
            offset = 0.0
        else:
            if not active:
                offset = principal(incoming) - incoming
            incoming += offset
        if not isinstance(outgoing, AutoTilt):
            if isinstance(point.incoming, AutoTilt):
                offset = principal(outgoing) - outgoing
            else:
                delta = outgoing - point.incoming
                if not isfinite(delta):
                    raise ConversionError(f"Tilt jump at pulse {point.pulse} exceeds numeric range")
                offset += principal(delta) - delta
            outgoing += offset
        result.append(replace(point, incoming=incoming, outgoing=outgoing))
        active = not isinstance(outgoing, AutoTilt)
    return tuple(result)


def convert_camera(
    camera: CameraInfo,
    timeline: Timeline,
    options: ConversionOptions,
    profile: VoxProfile,
    report: ReportBuilder,
    end_pulse: int,
    bpms: tuple[BpmEvent, ...],
) -> tuple[tuple[Controller, ...], tuple[VoxTiltMode, ...], int]:
    start = timeline.position(0)
    controllers: list[tuple[VoxPosition, int, Controller]] = [
        (start, 0, Realize(start, 3, *profile.radius_anchors)),
        (start, 1, Realize(start, 4, *profile.rotation_anchors)),
        (start, 2, AirScale(start, False, 1, 0, 0, 1, 0, 0)),
        (start, 3, AirScale(start, True, 1, 0, 0, 2, 0, 0)),
    ]
    report.count("camera_realize_rows", 2)
    report.count("air_scale_rows", 2)
    end = end_pulse
    camera_end = max(
        (
            points[-1].pulse
            for points in (
                camera.zoom_top,
                camera.zoom_bottom,
                camera.rotation_deg,
                camera.center_split,
                camera.tilt,
            )
            if points
        ),
        default=-1,
    )
    if camera_end >= end:
        # Leave a visible outro for a camera anchor at the end of the chart.
        outro_seconds = Fraction(12, 5)
        outro_ticks = ceil(outro_seconds * 4 * Fraction(str(bpms[-1].bpm)) / 5)
        end = camera_end + outro_ticks * 5
    bpm_pulses = tuple(event.pulse for event in bpms)

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
        controllers.append((row.position, len(controllers), row))
        end = max(end, span.pulse + span.duration)

    radius = Normalization(*profile.radius_anchors)
    rotation = Normalization(*profile.rotation_anchors)
    for name, points in (("zoom_bottom", camera.zoom_bottom), ("zoom_top", camera.zoom_top)):
        path = f"/camera/cam/body/{name}"
        for point in points:
            timeline.position(point.pulse)
            end = max(end, point.pulse)
        report.count(f"{name}_points", len(points))
        if points:
            report.record(
                name,
                FeatureStatus.APPROXIMATED,
                path,
            )
            if any(p.control.curved for p in points[:-1]):
                report.record(
                    name,
                    FeatureStatus.APPROXIMATED,
                    path,
                )

    for span in zoom_spans(
        camera.zoom_bottom, camera.zoom_top, radius, rotation, options.curve_step
    ):
        for name, normalization, first, last in (
            (ControllerName.RADIUS, radius, span.start.radius, span.end.radius),
            (ControllerName.ROTATION_X, rotation, span.start.pitch, span.end.pitch),
        ):
            add(
                Span(
                    span.pulse,
                    span.duration,
                    normalization.encode(first),
                    normalization.encode(last),
                ),
                name,
                1,
            )
            report.count("camera_rows")

    for feature, points, name, scale, code, message in (
        (
            "center_split",
            camera.center_split,
            ControllerName.MORPHING_2,
            CENTER_SPLIT_SCALE,
            "CENTER_SPLIT_MAPPING",
            "Center split uses Morphing2; playback is unverified.",
        ),
        (
            "rotation_deg",
            camera.rotation_deg,
            ControllerName.ROTATION_Z,
            1.0,
            "ROTATION_DEG_MAPPING",
            "Rotation uses BIL_RotZ; playback is unverified.",
        ),
    ):
        if not points:
            continue
        rows = body_graph(points, timeline, options.curve_step, bpm_pulses, name, scale)
        for row in rows:
            controllers.append((row.position, len(controllers), row))
        end = max(end, points[-1].pulse)
        report.count(f"{feature}_points", len(points))
        report.count(f"{feature}_rows", len(rows))
        report.record(
            feature,
            FeatureStatus.APPROXIMATED,
            f"/camera/cam/body/{feature}",
            code=code,
            message=message,
        )

    tilt = rebase_tilt(camera.tilt)
    if tilt != camera.tilt:
        report.record(
            "manual_tilt",
            FeatureStatus.CONVERTED,
            "/camera/tilt",
        )

    supported_modes = {AutoTilt.NORMAL: 0, AutoTilt.BIGGER: 1, AutoTilt.KEEP_BIGGER: 2}
    modes: list[tuple[int, int]] = []
    for i, point in enumerate(tilt):
        timeline.position(point.pulse)
        end = max(end, point.pulse)
        for value in dict.fromkeys((point.incoming, point.outgoing)):
            if isinstance(value, AutoTilt):
                if value in supported_modes:
                    modes.append((point.pulse, supported_modes[value]))
                elif value != AutoTilt.ZERO:
                    report.record(
                        "tilt_mode",
                        FeatureStatus.UNSUPPORTED,
                        f"/camera/tilt/{i}",
                        code="UNSUPPORTED_TILT_MODE",
                        message=f"Automatic tilt mode {value.value!r} is not mapped.",
                        pulse=point.pulse,
                    )
    runs: list[list[Span]] = []
    manual: list[Span] | None = None
    for i, current in enumerate(tilt):
        following = tilt[i + 1] if i + 1 < len(tilt) else None
        stop = following.pulse if following else end
        if isinstance(current.outgoing, AutoTilt):
            manual = None
            if current.outgoing == AutoTilt.ZERO and stop > current.pulse:
                runs.append([Span(current.pulse, stop - current.pulse, 0, 0)])
            continue
        if manual is None:
            manual = []
            runs.append(manual)
        if not isinstance(current.incoming, AutoTilt) and current.incoming != current.outgoing:
            manual.append(Span(current.pulse, 0, current.incoming, current.outgoing))
        if stop == current.pulse:
            continue
        # A numeric value remains manual, including zero, until an automatic setting.
        if following is None or isinstance(following.incoming, AutoTilt):
            manual.append(
                Span(current.pulse, stop - current.pulse, current.outgoing, current.outgoing)
            )
            continue
        samples = anchors(
            current.pulse,
            stop,
            current.outgoing,
            following.incoming,
            current.control,
            options.curve_step,
        )
        manual.extend(Span(y0, y1 - y0, v0, v1) for (y0, v0), (y1, v1) in pairwise(samples))
    for run in runs:
        for i, span in enumerate(run):
            if len(run) == 1:
                node = TiltNode.SINGLE
            elif i == 0:
                node = TiltNode.START
            elif i == len(run) - 1:
                node = TiltNode.END
            else:
                node = TiltNode.CONTINUE
            add(span, ControllerName.TILT, MANUAL_TILT_SCALE, node)
            report.count("manual_tilt_rows")
    if any(point.outgoing == AutoTilt.ZERO for point in tilt):
        report.record(
            "tilt_mode",
            FeatureStatus.APPROXIMATED,
            "/camera/tilt",
        )
    if any(not isinstance(point.incoming, AutoTilt) for point in camera.tilt):
        report.record(
            "manual_tilt",
            FeatureStatus.APPROXIMATED,
            "/camera/tilt",
        )
        if any(point.control.curved for point in camera.tilt[:-1]):
            report.record(
                "manual_tilt_curve",
                FeatureStatus.APPROXIMATED,
                "/camera/tilt",
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
