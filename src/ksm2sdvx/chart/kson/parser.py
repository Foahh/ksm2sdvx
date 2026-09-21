"""Decode KSON wire forms once; conversion never inspects JSON."""

import json
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import cast

from ksm2sdvx.chart.errors import KsonDecodeError, KsonValidationError, UnsupportedFormatError
from ksm2sdvx.chart.kson.model import (
    AudioInfo,
    AutoTilt,
    BeatInfo,
    BgmInfo,
    BpmEvent,
    ButtonNote,
    CameraInfo,
    ChipKeySound,
    CompatibilityInfo,
    CurveControl,
    EffectDefinition,
    EffectGroup,
    EffectInvocation,
    EffectParameterChange,
    Extension,
    GraphPoint,
    KeySoundInfo,
    KsonChart,
    LaserSection,
    Metadata,
    MeterEvent,
    NoteInfo,
    NumericAudioEvent,
    ParsedKson,
    RelativeGraphPoint,
    SpinEvent,
    SpinKind,
    StopEvent,
    TiltEvent,
)
from ksm2sdvx.chart.kson.validation import check, ordered, validate_graph, validate_kson
from ksm2sdvx.chart.types import KsonDuration, KsonPulse, MeasureIndex
from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue, Milliseconds
from ksm2sdvx.resources.models import ResourceReference


def pointer(path: str, key: str | int) -> str:
    return f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"


def _freeze(value: object, path: str = "") -> JsonValue:
    if value is None:
        raise KsonValidationError("null is not permitted in KSON", path)
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise KsonValidationError("numbers must be finite", path)
        return value
    if isinstance(value, list):
        return tuple(_freeze(v, pointer(path, i)) for i, v in enumerate(cast(list[object], value)))
    if isinstance(value, dict):
        return MappingProxyType(
            {k: _freeze(v, pointer(path, k)) for k, v in cast(dict[str, object], value).items()}
        )
    raise KsonValidationError("invalid JSON value", path)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KsonDecodeError(f"Duplicate JSON member: {key!r}")
        result[key] = value
    return result


def obj(value: JsonValue, path: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise KsonValidationError("expected an object", path)
    return value


def arr(value: JsonValue, path: str, lengths: tuple[int, ...] = ()) -> tuple[JsonValue, ...]:
    if not isinstance(value, tuple) or (lengths and len(value) not in lengths):
        raise KsonValidationError(
            f"expected an array{f' of length {lengths}' if lengths else ''}", path
        )
    return value


def integer(value: JsonValue, path: str, minimum: int | None = 0) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise KsonValidationError(
            f"expected an integer >= {minimum}" if minimum is not None else "expected an integer",
            path,
        )
    return value


def number(value: JsonValue, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsonValidationError("expected a finite number", path)
    try:
        result = float(value)
    except OverflowError as exc:
        raise KsonValidationError("number exceeds floating point range", path) from exc
    if not math.isfinite(result):
        raise KsonValidationError("expected a finite number", path)
    return result


def string(value: JsonValue, path: str) -> str:
    if not isinstance(value, str):
        raise KsonValidationError("expected a string", path)
    return value


def required(data: Mapping[str, JsonValue], key: str, path: str) -> JsonValue:
    if key not in data:
        raise KsonValidationError("required field is missing", pointer(path, key))
    return data[key]


def control(value: JsonValue, path: str) -> CurveControl:
    values = arr(value, path, (2,))
    return CurveControl(number(values[0], pointer(path, 0)), number(values[1], pointer(path, 1)))


def graph(value: JsonValue, path: str) -> tuple[GraphPoint, ...]:
    result: list[GraphPoint] = []
    for i, raw in enumerate(arr(value, path)):
        p = pointer(path, i)
        row = arr(raw, p, (2, 3))
        pulse = KsonPulse(integer(row[0], pointer(p, 0)))
        values = arr(row[1], pointer(p, 1), (2,)) if isinstance(row[1], tuple) else (row[1], row[1])
        result.append(
            GraphPoint(
                pulse,
                number(values[0], pointer(p, 1)),
                number(values[1], pointer(p, 1)),
                control(row[2], pointer(p, 2)) if len(row) == 3 else CurveControl(),
            )
        )
    return tuple(result)


class Parser:
    def __init__(self) -> None:
        self.extensions: list[Extension] = []
        self.assets: list[ResourceReference] = []

    def object(
        self, value: JsonValue, path: str, known: tuple[str, ...]
    ) -> Mapping[str, JsonValue]:
        data = obj(value, path)
        self.extensions.extend(
            Extension(pointer(path, k), v) for k, v in data.items() if k not in known
        )
        return data

    def asset(self, value: JsonValue, path: str, role: str, *, presets: bool = False) -> str:
        name = string(value, path)
        if not name:
            raise KsonValidationError("asset reference cannot be empty", path)
        preset = presets and not Path(name).suffix and not any(c in name for c in "/\\:")
        self.assets.append(ResourceReference(name, role, path, preset))
        return name

    def metadata(self, value: JsonValue) -> Metadata:
        path = "/meta"
        text_options = (
            "title_translit",
            "title_img_filename",
            "artist_translit",
            "artist_img_filename",
            "jacket_filename",
            "jacket_author",
            "icon_filename",
            "information",
        )
        fields = ("title", "artist", "chart_author", "difficulty", "level", "disp_bpm")
        data = self.object(value, path, fields + text_options + ("std_bpm",))
        title, artist, author = (
            string(required(data, k, path), pointer(path, k)) for k in fields[:3]
        )
        difficulty = required(data, "difficulty", path)
        difficulty = (
            string(difficulty, "/meta/difficulty")
            if isinstance(difficulty, str)
            else integer(difficulty, "/meta/difficulty")
        )
        optional: list[Extension] = []
        for key in (*text_options, "std_bpm"):
            if key in data:
                p = pointer(path, key)
                if key == "std_bpm":
                    if number(data[key], p) <= 0:
                        raise KsonValidationError("BPM must be positive", p)
                elif key.endswith("filename"):
                    self.asset(
                        data[key],
                        p,
                        key.removesuffix("_filename"),
                        presets=key in ("jacket_filename", "icon_filename"),
                    )
                else:
                    string(data[key], p)
                optional.append(Extension(p, data[key]))
        return Metadata(
            title,
            artist,
            author,
            difficulty,
            integer(required(data, "level", path), "/meta/level", 1),
            string(data.get("disp_bpm", ""), "/meta/disp_bpm"),
            tuple(optional),
        )

    def beat(self, value: JsonValue) -> BeatInfo:
        data = self.object(value, "/beat", ("bpm", "time_sig", "scroll_speed", "stop"))
        bpms: list[BpmEvent] = []
        for i, raw in enumerate(arr(required(data, "bpm", "/beat"), "/beat/bpm")):
            path = f"/beat/bpm/{i}"
            row = arr(raw, path, (2,))
            bpms.append(
                BpmEvent(KsonPulse(integer(row[0], path + "/0")), number(row[1], path + "/1"))
            )
        meters: list[MeterEvent] = []
        for i, raw in enumerate(arr(data.get("time_sig", ((0, (4, 4)),)), "/beat/time_sig")):
            p = f"/beat/time_sig/{i}"
            row = arr(raw, p, (2,))
            sig = arr(row[1], p + "/1", (2,))
            meters.append(
                MeterEvent(
                    MeasureIndex(integer(row[0], p + "/0")),
                    integer(sig[0], p + "/1/0", 1),
                    integer(sig[1], p + "/1/1", 1),
                )
            )
        stops: list[StopEvent] = []
        for i, raw in enumerate(arr(data.get("stop", ()), "/beat/stop")):
            p = f"/beat/stop/{i}"
            row = arr(raw, p, (2,))
            stops.append(
                StopEvent(
                    KsonPulse(integer(row[0], p + "/0")), KsonDuration(integer(row[1], p + "/1"))
                )
            )
        return BeatInfo(
            tuple(bpms),
            tuple(meters),
            graph(data.get("scroll_speed", ((0, 1.0),)), "/beat/scroll_speed"),
            tuple(stops),
        )

    def buttons(self, value: JsonValue, path: str) -> tuple[ButtonNote, ...]:
        notes: list[ButtonNote] = []
        for i, raw in enumerate(arr(value, path)):
            p = pointer(path, i)
            row = arr(raw, p, (2,)) if isinstance(raw, tuple) else (raw, 0)
            notes.append(
                ButtonNote(
                    KsonPulse(integer(row[0], p + "/0")), KsonDuration(integer(row[1], p + "/1"))
                )
            )
        return tuple(notes)

    def lasers(self, value: JsonValue, path: str) -> tuple[LaserSection, ...]:
        sections: list[LaserSection] = []
        for i, raw in enumerate(arr(value, path)):
            p = pointer(path, i)
            row = arr(raw, p, (2, 3))
            points = tuple(
                RelativeGraphPoint(KsonDuration(g.pulse), g.incoming, g.outgoing, g.control)
                for g in graph(row[1], p + "/1")
            )
            sections.append(
                LaserSection(
                    KsonPulse(integer(row[0], p + "/0")),
                    points,
                    integer(row[2], p + "/2", 1) if len(row) == 3 else 1,
                )
            )
        return tuple(sections)

    def notes(self, value: JsonValue) -> NoteInfo:
        data = self.object(value, "/note", ("bt", "fx", "laser"))
        bt = arr(data.get("bt", ((), (), (), ())), "/note/bt", (4,))
        fx = arr(data.get("fx", ((), ())), "/note/fx", (2,))
        laser = arr(data.get("laser", ((), ())), "/note/laser", (2,))
        return NoteInfo(
            (
                self.buttons(bt[0], "/note/bt/0"),
                self.buttons(bt[1], "/note/bt/1"),
                self.buttons(bt[2], "/note/bt/2"),
                self.buttons(bt[3], "/note/bt/3"),
            ),
            (self.buttons(fx[0], "/note/fx/0"), self.buttons(fx[1], "/note/fx/1")),
            (self.lasers(laser[0], "/note/laser/0"), self.lasers(laser[1], "/note/laser/1")),
        )

    def tilt(self, value: JsonValue, path: str) -> TiltEvent:
        row = arr(value, path, (2,))
        pulse = KsonPulse(integer(row[0], path + "/0"))
        raw = row[1]
        curve = CurveControl()
        if isinstance(raw, str):
            try:
                mode = AutoTilt(raw)
            except ValueError as exc:
                raise KsonValidationError("unknown automatic tilt mode", path + "/1") from exc
            return TiltEvent(pulse, mode, mode)
        if not isinstance(raw, tuple):
            v = number(raw, path + "/1")
            return TiltEvent(pulse, v, v)
        first, second = arr(raw, path + "/1", (2,))
        if isinstance(first, tuple):
            pair = arr(first, path + "/1/0", (2,))
            return TiltEvent(
                pulse, number(pair[0], path), number(pair[1], path), control(second, path + "/1/1")
            )
        incoming = number(first, path + "/1/0")
        if isinstance(second, str):
            try:
                outgoing: float | AutoTilt = AutoTilt(second)
            except ValueError as exc:
                raise KsonValidationError("unknown automatic tilt mode", path + "/1/1") from exc
        elif isinstance(second, tuple):
            outgoing, curve = incoming, control(second, path + "/1/1")
        else:
            outgoing = number(second, path + "/1/1")
        return TiltEvent(pulse, incoming, outgoing, curve)

    def camera(self, value: JsonValue) -> CameraInfo:
        data = self.object(value, "/camera", ("cam", "tilt"))
        cam = self.object(data.get("cam", {}), "/camera/cam", ("body", "pattern"))
        body = self.object(
            cam.get("body", {}),
            "/camera/cam/body",
            ("zoom_top", "zoom_bottom", "zoom_side", "rotation_deg", "center_split"),
        )
        graphs = {
            k: graph(v, f"/camera/cam/body/{k}")
            for k, v in body.items()
            if k in ("zoom_top", "zoom_bottom", "zoom_side", "rotation_deg", "center_split")
        }
        for key, points in graphs.items():
            validate_graph(points, f"/camera/cam/body/{key}")
        unsupported = [
            Extension(f"/camera/cam/body/{k}", body[k]) for k in ("zoom_side",) if graphs.get(k)
        ]
        pattern = self.object(cam.get("pattern", {}), "/camera/cam/pattern", ("laser",))
        laser = self.object(pattern.get("laser", {}), "/camera/cam/pattern/laser", ("slam_event",))
        base = "/camera/cam/pattern/laser/slam_event"
        slam = self.object(laser.get("slam_event", {}), base, ("spin", "half_spin", "swing"))
        spins: list[SpinEvent] = []
        for kind in SpinKind:
            for i, raw in enumerate(arr(slam.get(kind.value, ()), f"{base}/{kind.value}")):
                p = f"{base}/{kind.value}/{i}"
                row = arr(raw, p, (3,))
                spins.append(
                    SpinEvent(
                        KsonPulse(integer(row[0], p + "/0")),
                        integer(row[1], p + "/1", None),
                        KsonDuration(integer(row[2], p + "/2")),
                        kind,
                        p,
                    )
                )
        swings = arr(slam.get("swing", ()), base + "/swing")
        swing_pulses: list[int] = []
        for i, raw in enumerate(swings):
            p = f"{base}/swing/{i}"
            row = arr(raw, p, (3, 4))
            swing_pulses.append(integer(row[0], p + "/0"))
            check(integer(row[1], p + "/1", None) in (-1, 1), "direction must be -1 or 1", p + "/1")
            integer(row[2], p + "/2", 1)
            if len(row) == 4:
                params = self.object(row[3], p + "/3", ("scale", "repeat", "decay_order"))
                number(params.get("scale", 250.0), p + "/3/scale")
                integer(params.get("repeat", 3), p + "/3/repeat")
                check(
                    integer(params.get("decay_order", 2), p + "/3/decay_order") <= 2,
                    "decay_order must be 0..2",
                    p + "/3/decay_order",
                )
        ordered(swing_pulses, base + "/swing")
        if swings:
            unsupported.append(Extension(base + "/swing", slam["swing"]))
        tilts = tuple(
            self.tilt(v, f"/camera/tilt/{i}")
            for i, v in enumerate(arr(data.get("tilt", ()), "/camera/tilt"))
        )
        return CameraInfo(
            zoom_top=graphs.get("zoom_top", ()),
            zoom_bottom=graphs.get("zoom_bottom", ()),
            rotation_deg=graphs.get("rotation_deg", ()),
            center_split=graphs.get("center_split", ()),
            tilt=tilts,
            spins=tuple(spins),
            unsupported=tuple(unsupported),
        )

    def effects(self, value: JsonValue, path: str, *, fx: bool) -> EffectGroup:
        data = self.object(
            value,
            path,
            ("def", "param_change", "long_event")
            if fx
            else ("def", "param_change", "pulse_event", "peaking_filter_delay", "legacy"),
        )
        definitions: list[EffectDefinition] = []
        for i, raw in enumerate(arr(data.get("def", ()), path + "/def")):
            p = f"{path}/def/{i}"
            row = arr(raw, p, (2,))
            definition = self.object(row[1], p + "/1", ("type", "v"))
            kind = string(required(definition, "type", p + "/1"), p + "/1/type")
            params = self.parameters(definition.get("v", {}), p + "/1/v")
            if kind == "switch_audio":
                for key, name in params:
                    if key == "filename":
                        self.asset(name, p + "/1/v/filename", "effect_audio")
            definitions.append(EffectDefinition(string(row[0], p + "/0"), kind, params))
        changes: list[EffectParameterChange] = []
        for name, params in obj(data.get("param_change", {}), path + "/param_change").items():
            p = pointer(path + "/param_change", name)
            for key, events in obj(params, p).items():
                q = pointer(p, key)
                for i, raw in enumerate(arr(events, q)):
                    row = arr(raw, pointer(q, i), (2,))
                    changes.append(
                        EffectParameterChange(
                            name,
                            key,
                            KsonPulse(integer(row[0], pointer(q, i))),
                            string(row[1], pointer(q, i)),
                            pointer(q, i),
                        )
                    )
                    if key == "filename":
                        self.asset(row[1], pointer(q, i) + "/1", "effect_audio")
        invocations: list[EffectInvocation] = []
        event_key = "long_event" if fx else "pulse_event"
        for name, events in obj(data.get(event_key, {}), path + "/" + event_key).items():
            p = pointer(path + "/" + event_key, name)
            lanes = arr(events, p, (2,)) if fx else (events,)
            for lane, values in enumerate(lanes):
                q = pointer(p, lane) if fx else p
                for i, raw in enumerate(arr(values, q)):
                    r = pointer(q, i)
                    row: tuple[JsonValue, ...] = (
                        arr(raw, r, (2,)) if fx and isinstance(raw, tuple) else (raw, {})
                    )
                    params = self.parameters(row[1], r + "/1")
                    invocations.append(
                        EffectInvocation(
                            name, KsonPulse(integer(row[0], r)), lane if fx else None, params, r
                        )
                    )
                    for key, filename in params:
                        if key == "filename":
                            self.asset(filename, r + "/1/filename", "effect_audio")
        delay = Milliseconds(0)
        filter_gain: tuple[NumericAudioEvent, ...] = ()
        if "peaking_filter_delay" in data:
            delay = Milliseconds(
                integer(data["peaking_filter_delay"], path + "/peaking_filter_delay")
            )
            check(
                integer(data["peaking_filter_delay"], path + "/peaking_filter_delay") <= 160,
                "peaking filter delay must be 0..160 ms",
                path + "/peaking_filter_delay",
            )
        if "legacy" in data:
            legacy = self.object(data["legacy"], path + "/legacy", ("filter_gain",))
            if "filter_gain" in legacy:
                filter_gain = self.numeric_events(
                    legacy["filter_gain"], path + "/legacy/filter_gain"
                )
        return EffectGroup(
            tuple(definitions), tuple(changes), tuple(invocations), (), delay, filter_gain
        )

    def parameters(self, value: JsonValue, path: str) -> tuple[tuple[str, str], ...]:
        return tuple((k, string(v, pointer(path, k))) for k, v in obj(value, path).items())

    def numeric_events(self, value: JsonValue, path: str) -> tuple[NumericAudioEvent, ...]:
        pulses: list[int] = []
        events: list[NumericAudioEvent] = []
        for i, raw in enumerate(arr(value, path)):
            p = pointer(path, i)
            row = arr(raw, p, (2,))
            pulses.append(integer(row[0], p + "/0"))
            check(number(row[1], p + "/1") >= 0, "value must be nonnegative", p + "/1")
            events.append(NumericAudioEvent(KsonPulse(pulses[-1]), number(row[1], p + "/1"), p))
        ordered(pulses, path)
        return tuple(events)

    def key_sounds(self, value: JsonValue) -> KeySoundInfo:
        keys = self.object(value, "/audio/key_sound", ("fx", "laser"))
        chips: list[ChipKeySound] = []
        for lane_kind in ("fx", "laser"):
            p = f"/audio/key_sound/{lane_kind}"
            event_key = "chip_event" if lane_kind == "fx" else "slam_event"
            group = self.object(
                keys.get(lane_kind, {}),
                p,
                (event_key,) if lane_kind == "fx" else (event_key, "vol", "legacy"),
            )
            if "vol" in group:
                self.numeric_events(group["vol"], p + "/vol")
            if "legacy" in group:
                legacy = self.object(group["legacy"], p + "/legacy", ("vol_auto",))
                check(
                    type(legacy.get("vol_auto", False)) is bool,
                    "expected boolean",
                    p + "/legacy/vol_auto",
                )
            events = obj(group.get(event_key, {}), p + "/" + event_key)
            builtins = (
                ("clap", "clap_impact", "clap_punchy", "snare", "snare_lo")
                if lane_kind == "fx"
                else ("slam_up", "slam_down", "slam_swing", "slam_mute")
            )
            for name, raw_events in events.items():
                q = pointer(p + "/" + event_key, name)
                if name not in builtins:
                    self.asset(name, q, "keysound")
                lanes = arr(raw_events, q, (2,)) if lane_kind == "fx" else (raw_events,)
                for lane, values in enumerate(lanes):
                    r = pointer(q, lane) if lane_kind == "fx" else q
                    pulses: list[int] = []
                    for i, raw in enumerate(arr(values, r)):
                        s = pointer(r, i)
                        volume = 1.0
                        if lane_kind == "fx" and isinstance(raw, tuple):
                            row = arr(raw, s, (2,))
                            pulses.append(integer(row[0], s + "/0"))
                            params = self.object(row[1], s + "/1", ("vol",))
                            check(
                                number(params.get("vol", 1.0), s + "/1/vol") >= 0,
                                "volume must be nonnegative",
                                s + "/1/vol",
                            )
                            volume = number(params.get("vol", 1.0), s + "/1/vol")
                        else:
                            pulses.append(integer(raw, s))
                        if lane_kind == "fx":
                            chips.append(
                                ChipKeySound(
                                    KsonPulse(pulses[-1]), lane, name, volume, name in builtins, s
                                )
                            )
                    ordered(pulses, r)
        laser = keys.get("laser", {})
        return KeySoundInfo(
            tuple(chips), (Extension("/audio/key_sound/laser", laser),) if laser else ()
        )

    def audio(self, value: JsonValue) -> AudioInfo:
        data = self.object(value, "/audio", ("bgm", "audio_effect", "key_sound"))
        bgm: BgmInfo | None = None
        if "bgm" in data:
            b = self.object(
                data["bgm"], "/audio/bgm", ("filename", "vol", "offset", "preview", "legacy")
            )
            preview = self.object(
                b.get("preview", {}), "/audio/bgm/preview", ("offset", "duration")
            )
            legacy = self.object(b.get("legacy", {}), "/audio/bgm/legacy", ("fp_filenames",))
            files = tuple(
                self.asset(v, f"/audio/bgm/legacy/fp_filenames/{i}", "prerendered_audio")
                for i, v in enumerate(
                    arr(legacy.get("fp_filenames", ()), "/audio/bgm/legacy/fp_filenames")
                )
            )
            bgm = BgmInfo(
                self.asset(b["filename"], "/audio/bgm/filename", "music")
                if "filename" in b
                else None,
                number(b.get("vol", 1.0), "/audio/bgm/vol"),
                Milliseconds(integer(b.get("offset", 0), "/audio/bgm/offset", None)),
                Milliseconds(integer(preview.get("offset", 0), "/audio/bgm/preview/offset")),
                Milliseconds(
                    integer(preview.get("duration", 15000), "/audio/bgm/preview/duration")
                ),
                files,
            )
        effects = self.object(data.get("audio_effect", {}), "/audio/audio_effect", ("fx", "laser"))
        keys = self.key_sounds(data.get("key_sound", {}))
        return AudioInfo(
            bgm,
            self.effects(effects.get("fx", {}), "/audio/audio_effect/fx", fx=True),
            self.effects(effects.get("laser", {}), "/audio/audio_effect/laser", fx=False),
            keys,
        )

    def retained_assets(self, value: JsonValue, path: str) -> None:
        """Inventory specified background filenames without interpreting renderer metadata."""
        if isinstance(value, Mapping):
            for key, item in value.items():
                p = pointer(path, key)
                if key == "filename":
                    self.asset(item, p, "background", presets="/movie/" not in p)
                else:
                    self.retained_assets(item, p)
        elif isinstance(value, tuple):
            for i, item in enumerate(value):
                self.retained_assets(item, pointer(path, i))

    def chart(self, value: JsonValue) -> KsonChart:
        data = self.object(
            value,
            "",
            (
                "format_version",
                "meta",
                "beat",
                "note",
                "camera",
                "audio",
                "bg",
                "gauge",
                "editor",
                "compat",
                "impl",
            ),
        )
        version = integer(required(data, "format_version", ""), "/format_version")
        if version != 1:
            raise UnsupportedFormatError(f"Unsupported KSON format_version: {version}")
        meta = self.metadata(required(data, "meta", ""))
        beat = self.beat(required(data, "beat", ""))
        notes = self.notes(data.get("note", {}))
        camera = self.camera(data.get("camera", {}))
        audio = self.audio(data.get("audio", {}))
        compat = obj(data.get("compat", {}), "/compat")
        compatibility = CompatibilityInfo(
            string(compat.get("ksh_version", ""), "/compat/ksh_version")
        )
        retained: list[Extension] = []
        for key in ("bg", "gauge", "editor", "compat", "impl"):
            if key in data:
                obj(data[key], f"/{key}")
                if key == "gauge":
                    gauge = self.object(data[key], "/gauge", ("total",))
                    total = integer(gauge.get("total", 0), "/gauge/total")
                    check(
                        total == 0 or total >= 100,
                        "gauge total must be zero or >= 100",
                        "/gauge/total",
                    )
                retained.append(Extension(f"/{key}", data[key]))
                if key == "bg":
                    self.retained_assets(data[key], "/bg")
        return KsonChart(
            meta,
            beat,
            notes,
            camera,
            audio,
            tuple(self.assets),
            tuple(retained),
            tuple(self.extensions),
            compatibility=compatibility,
        )


def parse_kson(text: str) -> ParsedKson:
    diagnostics: list[Diagnostic] = []
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        raw: object = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, RecursionError) as exc:
        raise KsonDecodeError(str(exc)) from exc
    try:
        chart = Parser().chart(_freeze(raw))
    except RecursionError as exc:
        raise KsonDecodeError("JSON nesting exceeds the supported depth") from exc
    validate_kson(chart)
    return ParsedKson(chart, tuple(diagnostics))


def load_kson(path: Path) -> ParsedKson:
    try:
        result = parse_kson(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise KsonDecodeError(f"{path}: {exc}") from exc
    return replace(
        result, diagnostics=tuple(replace(d, source_path=str(path)) for d in result.diagnostics)
    )
