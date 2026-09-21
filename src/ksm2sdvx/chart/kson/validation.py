"""Source invariants, also checked for programmatically constructed charts."""

import math
import re
from collections.abc import Iterable

from ksm2sdvx.chart.errors import KsonValidationError, UnsupportedFormatError
from ksm2sdvx.chart.kson.model import (
    AutoTilt,
    CurveControl,
    GraphPoint,
    KsonChart,
    RelativeGraphPoint,
)


def check(condition: bool, message: str, path: str) -> None:
    if not condition:
        raise KsonValidationError(message, path)


def uint(value: int, path: str, minimum: int = 0) -> None:
    check(type(value) is int and value >= minimum, f"expected integer >= {minimum}", path)


def finite(value: float, path: str) -> None:
    check(type(value) in (int, float), "expected number", path)
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    check(valid, "number must be finite", path)


def ordered(values: Iterable[int], path: str) -> None:
    previous = -1
    for i, value in enumerate(values):
        uint(value, f"{path}/{i}/0")
        check(value > previous, "positions must be strictly increasing", f"{path}/{i}/0")
        previous = value


def validate_control(control: CurveControl, path: str) -> None:
    for value in (control.x, control.y):
        finite(value, path)
        check(0 <= value <= 1, "curve control outside 0..1", path)


def validate_graph(points: tuple[GraphPoint, ...], path: str) -> None:
    ordered((p.pulse for p in points), path)
    for i, point in enumerate(points):
        validate_point(point, f"{path}/{i}")


def validate_point(point: GraphPoint | RelativeGraphPoint, path: str) -> None:
    finite(point.incoming, path + "/1")
    finite(point.outgoing, path + "/1")
    validate_control(point.control, path + "/2")


def validate_kson(chart: KsonChart) -> None:
    if type(chart.format_version) is not int or chart.format_version != 1:
        raise UnsupportedFormatError(f"Unsupported KSON format_version: {chart.format_version}")
    check(type(chart.compatibility.ksh_version) is str, "expected string", "/compat/ksh_version")
    meta = chart.meta
    for name, value in (
        ("title", meta.title),
        ("artist", meta.artist),
        ("chart_author", meta.chart_author),
        ("disp_bpm", meta.disp_bpm),
    ):
        check(type(value) is str, "expected string", f"/meta/{name}")
    check(
        bool(re.fullmatch(r"[0-9.\-]*", meta.disp_bpm)), "invalid displayed BPM", "/meta/disp_bpm"
    )
    uint(meta.level, "/meta/level", 1)
    check(meta.level <= 20, "level must be 1..20", "/meta/level")
    if not isinstance(meta.difficulty, str):
        uint(meta.difficulty, "/meta/difficulty")
        check(meta.difficulty <= 3, "difficulty index must be 0..3", "/meta/difficulty")
    beat = chart.beat
    check(
        bool(beat.bpm) and beat.bpm[0].pulse == 0, "initial BPM at pulse 0 is required", "/beat/bpm"
    )
    ordered((event.pulse for event in beat.bpm), "/beat/bpm")
    for i, event in enumerate(beat.bpm):
        finite(event.bpm, f"/beat/bpm/{i}/1")
        check(event.bpm > 0, "BPM must be positive", f"/beat/bpm/{i}/1")
    check(
        bool(beat.time_signatures) and beat.time_signatures[0].measure == 0,
        "initial meter at measure 0 is required",
        "/beat/time_sig",
    )
    ordered((event.measure for event in beat.time_signatures), "/beat/time_sig")
    for i, event in enumerate(beat.time_signatures):
        uint(event.numerator, f"/beat/time_sig/{i}/1/0", 1)
        uint(event.denominator, f"/beat/time_sig/{i}/1/1", 1)
    validate_graph(beat.scroll_speed, "/beat/scroll_speed")
    ordered((event.pulse for event in beat.stops), "/beat/stop")
    for i, stop in enumerate(beat.stops):
        uint(stop.duration, f"/beat/stop/{i}/1")
    for name, lanes, count in (("bt", chart.note.bt, 4), ("fx", chart.note.fx, 2)):
        check(len(lanes) == count, f"expected {count} lanes", f"/note/{name}")
        for lane_index, lane in enumerate(lanes):
            path = f"/note/{name}/{lane_index}"
            ordered((note.pulse for note in lane), path)
            end = 0
            for i, note in enumerate(lane):
                uint(note.duration, f"{path}/{i}/1")
                check(note.pulse >= end, "notes overlap", f"{path}/{i}")
                end = note.pulse + note.duration
    check(len(chart.note.laser) == 2, "expected 2 lanes", "/note/laser")
    for lane_index, lane in enumerate(chart.note.laser):
        path = f"/note/laser/{lane_index}"
        ordered((section.pulse for section in lane), path)
        end = 0
        for i, section in enumerate(lane):
            p = f"{path}/{i}"
            uint(section.width, p + "/2", 1)
            check(section.width in (1, 2), "laser width must be 1 or 2", p + "/2")
            check(bool(section.points), "laser section must contain points", p + "/1")
            check(section.points[0].offset == 0, "first laser offset must be zero", p + "/1/0/0")
            check(section.pulse >= end, "laser sections overlap", p)
            ordered((point.offset for point in section.points), p + "/1")
            for j, point in enumerate(section.points):
                validate_point(point, f"{p}/1/{j}")
                check(
                    0 <= point.incoming <= 1 and 0 <= point.outgoing <= 1,
                    "laser position outside 0..1",
                    f"{p}/1/{j}/1",
                )
            end = section.pulse + section.points[-1].offset
    camera = chart.camera
    validate_graph(camera.zoom_top, "/camera/cam/body/zoom_top")
    validate_graph(camera.zoom_bottom, "/camera/cam/body/zoom_bottom")
    validate_graph(camera.rotation_deg, "/camera/cam/body/rotation_deg")
    validate_graph(camera.center_split, "/camera/cam/body/center_split")
    ordered((point.pulse for point in camera.tilt), "/camera/tilt")
    for i, tilt in enumerate(camera.tilt):
        p = f"/camera/tilt/{i}"
        validate_control(tilt.control, p)
        for value in (tilt.incoming, tilt.outgoing):
            if not isinstance(value, AutoTilt):
                finite(value, p)
                check(-100 <= value <= 100, "manual tilt outside -100..100", p)
        check(
            not isinstance(tilt.incoming, AutoTilt) or tilt.incoming == tilt.outgoing,
            "automatic tilt must be a single mode",
            p,
        )
    for kind in ("spin", "half_spin"):
        ordered(
            (event.pulse for event in camera.spins if event.kind == kind),
            f"/camera/cam/pattern/laser/slam_event/{kind}",
        )
    for event in camera.spins:
        check(
            type(event.direction) is int and event.direction in (-1, 1),
            "direction must be -1 or 1",
            event.path,
        )
        uint(event.duration, event.path + "/2")
    if chart.audio.bgm:
        bgm = chart.audio.bgm
        finite(bgm.volume, "/audio/bgm/vol")
        check(bgm.volume >= 0, "volume must be nonnegative", "/audio/bgm/vol")
        check(type(bgm.offset) is int, "offset must be integer milliseconds", "/audio/bgm/offset")
        uint(bgm.preview_offset, "/audio/bgm/preview/offset")
        uint(bgm.preview_duration, "/audio/bgm/preview/duration")
    for name, group in (("fx", chart.audio.fx), ("laser", chart.audio.laser)):
        base = f"/audio/audio_effect/{name}"
        uint(group.peaking_filter_delay, base + "/peaking_filter_delay")
        check(
            group.peaking_filter_delay <= 160,
            "peaking filter delay must be 0..160 ms",
            base + "/peaking_filter_delay",
        )
        ordered((event.pulse for event in group.filter_gain), base + "/legacy/filter_gain")
        for event in group.filter_gain:
            finite(event.value, event.path)
            check(event.value >= 0, "value must be nonnegative", event.path)
        names = [definition.name for definition in group.definitions]
        check(
            len(set(names)) == len(names),
            "duplicate effect definition",
            f"/audio/audio_effect/{name}/def",
        )
        timelines: dict[tuple[str, str], list[int]] = {}
        for change in group.changes:
            check(
                change.parameter != "filename",
                "filename parameters can only be set in effect definitions",
                change.path,
            )
            timelines.setdefault((change.effect, change.parameter), []).append(change.pulse)
        for values in timelines.values():
            ordered(values, f"/audio/audio_effect/{name}/param_change")
        invokes: dict[tuple[str, int | None], list[int]] = {}
        for invocation in group.invocations:
            check(
                all(name != "filename" for name, _ in invocation.parameters),
                "filename parameters can only be set in effect definitions",
                invocation.path,
            )
            check(
                invocation.lane in (0, 1) if name == "fx" else invocation.lane is None,
                "effect invocation has an invalid lane",
                invocation.path,
            )
            invokes.setdefault((invocation.effect, invocation.lane), []).append(invocation.pulse)
        for values in invokes.values():
            ordered(values, f"/audio/audio_effect/{name}/events")
    chip_timelines: dict[tuple[str, int], list[int]] = {}
    for chip in chart.audio.key_sound.chips:
        check(type(chip.lane) is int and chip.lane in (0, 1), "expected FX lane 0 or 1", chip.path)
        check(type(chip.sample) is str and bool(chip.sample), "expected sample name", chip.path)
        finite(chip.volume, chip.path)
        check(chip.volume >= 0, "volume must be nonnegative", chip.path)
        check(type(chip.preset) is bool, "expected preset flag", chip.path)
        chip_timelines.setdefault((chip.sample, chip.lane), []).append(chip.pulse)
    for values in chip_timelines.values():
        ordered(values, "/audio/key_sound/fx/chip_event")
