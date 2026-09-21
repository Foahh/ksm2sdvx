"""VOX v13 data. Unknown fields keep column numbers, without inferred semantics.

Collections retain file order, including simultaneous nodes and controller rows.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.effects import EffectPair, LaserEffect, ParameterAssignment
from ksm2sdvx.chart.vox.scripts import Script, ScriptedTrack
from ksm2sdvx.common.types import Milliseconds


@dataclass(frozen=True, slots=True, order=True)
class VoxPosition:
    measure: int
    beat: int
    tick: VoxTick


class LaserMarker(IntEnum):
    CONTINUE = 0
    START = 1
    END = 2


class LaserCurve(IntEnum):
    LINEAR = 0
    UNKNOWN_1 = 1
    HERMITE = 2
    INTERPOLATED_LINEAR = 3
    SINE_EASE_OUT = 4
    SINE_EASE_IN = 5


class RollType(IntEnum):
    NONE = 0
    ROLL = 1
    ROLL_TWO_BEATS = 2
    ROLL_THREE_BEATS = 3
    TRIPLE_ROLL = 4
    SWING = 5
    ROLL_TENTHS = 6
    SWING_TENTHS = 7


class TiltMode(IntEnum):
    NORMAL = 0
    BIGGER = 1
    KEEP_BIGGER = 2


class TiltNode(IntEnum):
    CONTINUE = 0
    SINGLE = 1
    START = 2
    END = 3


class ControllerName(StrEnum):
    RADIUS = "CAM_Radi"
    ROTATION_X = "CAM_RotX"
    ROTATION_Z = "BIL_RotZ"
    TILT = "Tilt"
    MORPHING_2 = "Morphing2"


@dataclass(frozen=True, slots=True)
class VoxBtNote:
    position: VoxPosition
    duration: VoxTick
    unknown_c2: int = 0
    cells_per_chain: int | None = None


@dataclass(frozen=True, slots=True)
class VoxFxChip:
    position: VoxPosition
    sample: int = 0
    cells_per_chain: int | None = None


@dataclass(frozen=True, slots=True)
class VoxFxHold:
    position: VoxPosition
    duration: VoxTick
    effect_pair: int  # Wire index: 2..13, unlike ParameterAssignment.pair_index.
    cells_per_chain: int | None = None


@dataclass(frozen=True, slots=True)
class VoxLaserPoint:
    position: VoxPosition
    value: float
    marker: LaserMarker
    width: int
    roll_type: RollType = RollType.NONE
    effect: int = 0  # 0 peak, 1..5 TAB EFFECT entries, 6 AUTO TAB control source.
    unused_c6: int = 0
    curve_type: LaserCurve = LaserCurve.LINEAR
    unknown_c8: int = 0
    roll_length: int = 0  # C9; zero selects the roll type's default duration.
    # No C10: cells-per-chain meaning is explicitly unverified.


@dataclass(frozen=True, slots=True)
class VoxBpmEvent:
    position: VoxPosition
    bpm: float
    pause: bool = False


@dataclass(frozen=True, slots=True)
class BpmOptions:
    constant_scroll: bool
    representative_bpm: float


@dataclass(frozen=True, slots=True)
class VoxMeterEvent:
    position: VoxPosition
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class VoxTiltMode:
    position: VoxPosition
    mode: TiltMode


@dataclass(frozen=True, slots=True)
class Realize:
    position: VoxPosition
    controller: int
    c4: float
    c5: float
    c6: float
    c3: float = 0
    c7: float = 0


@dataclass(frozen=True, slots=True)
class AirScale:
    position: VoxPosition
    right: bool
    c2: int
    c3: float
    c4: float
    c5: float
    c6: float
    c7: float


@dataclass(frozen=True, slots=True)
class ControllerSpan:
    """Linear endpoints in controller units; BIL_RotZ uses degrees."""

    position: VoxPosition
    name: ControllerName
    duration: VoxTick
    start_value: float
    end_value: float
    node_type: TiltNode = TiltNode.CONTINUE
    start_mode: int = 2  # C2; 2 selects the explicit start value for body controls.
    unused_c7: float = 0


@dataclass(frozen=True, slots=True)
class ManualSpeed:
    """Instantaneous scroll multiplier; C4 is an f-prefixed float payload."""

    position: VoxPosition
    multiplier: float
    unknown_c2: int = 0


class OpaqueControllerName(StrEnum):
    """Commands whose complete payload layout is not specified."""

    LANE_Y = "LaneY"
    HUD_Y = "HudY"
    BAR_OFF = "BAROFF"
    BAR = "BAR"
    MORPHING_0 = "Morphing0"
    MORPHING_1 = "Morphing1"
    MORPHING_3 = "Morphing3"
    SPECIAL = "SpecialN"


type Field = str | int | float


@dataclass(frozen=True, slots=True)
class OpaqueController:
    position: VoxPosition
    name: OpaqueControllerName
    fields: tuple[Field, ...]  # C2 onward, retained without invented meanings.


type Controller = Realize | AirScale | ControllerSpan | ManualSpeed | OpaqueController
type TrackEvent = VoxBtNote | VoxFxChip | VoxFxHold | VoxLaserPoint


@dataclass(frozen=True, slots=True)
class VoxTrack:
    number: int
    events: tuple[TrackEvent, ...]


@dataclass(frozen=True, slots=True)
class AutoTabEvent:
    position: VoxPosition
    duration: VoxTick
    effect_pair: int  # 2-indexed, independent of parameter assignment row indices.


class PostEffectName(StrEnum):
    CHROMATIC_ABERRATION = "ChromaticAbberation"  # Wire spelling.
    CRT_MONITOR = "CrtMonitorEffect"
    SIMPLE_NOISE = "SimpleNoise"
    RADICAL_BLUR = "RadicalBlur"
    COLOR_CONVERSION = "ColorConversion"
    SET_FRAME_LABEL = "SetFrameLabel"
    LUMINOUS = "LuminousEffect"
    RANDOM_SHAKE = "RandomShake"


@dataclass(frozen=True, slots=True)
class CellDuration:
    value: VoxTick


@dataclass(frozen=True, slots=True)
class MillisecondDuration:
    value: Milliseconds


@dataclass(frozen=True, slots=True)
class PostEffect:
    position: VoxPosition
    duration: CellDuration | MillisecondDuration
    name: PostEffectName
    parameter: str
    start_value: float
    end_value: float
    unknown_c1: int = 2
    unknown_c4: int = 0
    unknown_c5: int = 0


@dataclass(frozen=True, slots=True)
class OpaqueRow:
    """Uninterpreted fields for LYRIC INFO and REVERB EFFECT PARAM."""

    fields: tuple[Field, ...]


@dataclass(frozen=True, slots=True)
class VoxChart:
    meters: tuple[VoxMeterEvent, ...]
    bpms: tuple[VoxBpmEvent, ...]
    tilt_modes: tuple[VoxTiltMode, ...]
    tracks: tuple[VoxTrack, ...]
    original_left: tuple[VoxLaserPoint, ...]
    original_right: tuple[VoxLaserPoint, ...]
    controllers: tuple[Controller, ...]
    end_position: VoxPosition
    laser_effects: tuple[LaserEffect, ...]
    fx_effects: tuple[EffectPair, ...]
    parameter_assignments: tuple[ParameterAssignment, ...]
    format_version: int = 13
    beat_resolution: int | None = None  # Omitted means 48 cells per quarter note.
    bpm_options: BpmOptions | None = None
    lyrics: tuple[OpaqueRow, ...] = ()
    reverb: tuple[OpaqueRow, ...] = ()
    auto_tab: tuple[AutoTabEvent, ...] = ()
    locked_controllers: tuple[Controller, ...] | None = None
    post_effects: tuple[PostEffect, ...] | None = None
    scripts: tuple[Script, ...] | None = None
    scripted_tracks: tuple[ScriptedTrack, ...] = ()

    @property
    def resolution(self) -> int:
        return 48 if self.beat_resolution is None else self.beat_resolution
