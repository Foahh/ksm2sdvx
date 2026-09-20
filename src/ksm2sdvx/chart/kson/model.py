"""Immutable, normalized KSON version 1 models."""

from dataclasses import dataclass
from enum import StrEnum

from ksm2sdvx.chart.types import KsonDuration, KsonPulse, MeasureIndex
from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue, Milliseconds
from ksm2sdvx.resources.models import ResourceReference


@dataclass(frozen=True, slots=True)
class Extension:
    path: str
    value: JsonValue


@dataclass(frozen=True, slots=True)
class Metadata:
    title: str
    artist: str
    chart_author: str
    difficulty: int | str
    level: int
    disp_bpm: str
    optional: tuple[Extension, ...] = ()


@dataclass(frozen=True, slots=True)
class CurveControl:
    x: float = 0.0
    y: float = 0.0

    @property
    def curved(self) -> bool:
        return abs(self.x - self.y) > 1e-12


@dataclass(frozen=True, slots=True)
class GraphPoint:
    pulse: KsonPulse
    incoming: float
    outgoing: float
    control: CurveControl = CurveControl()


@dataclass(frozen=True, slots=True)
class RelativeGraphPoint:
    offset: KsonDuration
    incoming: float
    outgoing: float
    control: CurveControl = CurveControl()


@dataclass(frozen=True, slots=True)
class BpmEvent:
    pulse: KsonPulse
    bpm: float


@dataclass(frozen=True, slots=True)
class MeterEvent:
    measure: MeasureIndex
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class StopEvent:
    pulse: KsonPulse
    duration: KsonDuration


@dataclass(frozen=True, slots=True)
class BeatInfo:
    bpm: tuple[BpmEvent, ...]
    time_signatures: tuple[MeterEvent, ...] = (MeterEvent(MeasureIndex(0), 4, 4),)
    scroll_speed: tuple[GraphPoint, ...] = (GraphPoint(KsonPulse(0), 1.0, 1.0),)
    stops: tuple[StopEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ButtonNote:
    pulse: KsonPulse
    duration: KsonDuration


@dataclass(frozen=True, slots=True)
class LaserSection:
    pulse: KsonPulse
    points: tuple[RelativeGraphPoint, ...]
    width: int = 1


type ButtonLane = tuple[ButtonNote, ...]
type LaserLane = tuple[LaserSection, ...]


@dataclass(frozen=True, slots=True)
class NoteInfo:
    bt: tuple[ButtonLane, ButtonLane, ButtonLane, ButtonLane] = ((), (), (), ())
    fx: tuple[ButtonLane, ButtonLane] = ((), ())
    laser: tuple[LaserLane, LaserLane] = ((), ())


class AutoTilt(StrEnum):
    NORMAL = "normal"
    BIGGER = "bigger"
    BIGGEST = "biggest"
    KEEP_NORMAL = "keep_normal"
    KEEP_BIGGER = "keep_bigger"
    KEEP_BIGGEST = "keep_biggest"
    ZERO = "zero"


@dataclass(frozen=True, slots=True)
class TiltEvent:
    pulse: KsonPulse
    incoming: float | AutoTilt
    outgoing: float | AutoTilt
    control: CurveControl = CurveControl()


class SpinKind(StrEnum):
    SPIN = "spin"
    HALF_SPIN = "half_spin"


@dataclass(frozen=True, slots=True)
class SpinEvent:
    pulse: KsonPulse
    direction: int
    duration: KsonDuration
    kind: SpinKind
    path: str


@dataclass(frozen=True, slots=True)
class CameraInfo:
    zoom_top: tuple[GraphPoint, ...] = ()
    zoom_bottom: tuple[GraphPoint, ...] = ()
    tilt: tuple[TiltEvent, ...] = ()
    spins: tuple[SpinEvent, ...] = ()
    unsupported: tuple[Extension, ...] = ()


@dataclass(frozen=True, slots=True)
class BgmInfo:
    filename: str | None = None
    volume: float = 1.0
    offset: Milliseconds = Milliseconds(0)
    preview_offset: Milliseconds = Milliseconds(0)
    preview_duration: Milliseconds = Milliseconds(15000)
    legacy_filenames: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    name: str
    kind: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class EffectParameterChange:
    effect: str
    parameter: str
    pulse: KsonPulse
    value: str
    path: str


@dataclass(frozen=True, slots=True)
class EffectInvocation:
    effect: str
    pulse: KsonPulse
    lane: int | None
    parameters: tuple[tuple[str, str], ...]
    path: str


@dataclass(frozen=True, slots=True)
class EffectGroup:
    definitions: tuple[EffectDefinition, ...] = ()
    changes: tuple[EffectParameterChange, ...] = ()
    invocations: tuple[EffectInvocation, ...] = ()
    retained: tuple[Extension, ...] = ()


@dataclass(frozen=True, slots=True)
class AudioInfo:
    bgm: BgmInfo | None = None
    fx: EffectGroup = EffectGroup()
    laser: EffectGroup = EffectGroup()
    key_sound: tuple[Extension, ...] = ()


@dataclass(frozen=True, slots=True)
class KsonChart:
    meta: Metadata
    beat: BeatInfo
    note: NoteInfo = NoteInfo()
    camera: CameraInfo = CameraInfo()
    audio: AudioInfo = AudioInfo()
    assets: tuple[ResourceReference, ...] = ()
    retained: tuple[Extension, ...] = ()
    extensions: tuple[Extension, ...] = ()
    format_version: int = 1


@dataclass(frozen=True, slots=True)
class ParsedKson:
    chart: KsonChart
    diagnostics: tuple[Diagnostic, ...] = ()
