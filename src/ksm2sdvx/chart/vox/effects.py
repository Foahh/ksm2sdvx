"""Typed effect rows; cN names preserve parameters without assuming their units."""

from dataclasses import dataclass, field
from enum import IntEnum


class FxEffectType(IntEnum):
    NONE = 0
    RETRIGGER = 1
    GATE = 2
    FLANGER = 3
    TAPE_STOP = 4
    SIDE_CHAIN = 5
    WOBBLE = 6
    BIT_CRUSHER = 7
    ECHO = 8
    PITCH_SHIFT = 9
    TAPE_STOP_EX = 10
    LOW_PASS = 11
    HIGH_PASS = 12
    PITCH_AND_SPEED = 13


class LaserEffectType(IntEnum):
    LOW_PASS = 1
    HIGH_PASS = 2
    BIT_CRUSHER = 3


@dataclass(frozen=True, slots=True)
class NoEffect:
    kind: FxEffectType = field(default=FxEffectType.NONE, init=False)
    c1: int = 0
    c2: int = 0
    c3: int = 0
    c4: int = 0
    c5: int = 0
    c6: int = 0


@dataclass(frozen=True, slots=True)
class Retrigger:
    kind: FxEffectType = field(default=FxEffectType.RETRIGGER, init=False)
    c1: int
    c2: float
    c3: float
    c4: float
    c5: float
    c6: float


@dataclass(frozen=True, slots=True)
class Gate:
    kind: FxEffectType = field(default=FxEffectType.GATE, init=False)
    c1: float
    c2: int
    c3: float


@dataclass(frozen=True, slots=True)
class Flanger:
    kind: FxEffectType = field(default=FxEffectType.FLANGER, init=False)
    c1: float
    c2: float
    c3: float
    c4: int
    c5: float


@dataclass(frozen=True, slots=True)
class TapeStop:
    kind: FxEffectType = field(default=FxEffectType.TAPE_STOP, init=False)
    c1: float
    c2: float
    c3: float


@dataclass(frozen=True, slots=True)
class SideChain:
    kind: FxEffectType = field(default=FxEffectType.SIDE_CHAIN, init=False)
    c1: float
    c2: float
    c3: int
    c4: int
    c5: int


@dataclass(frozen=True, slots=True)
class Wobble:
    kind: FxEffectType = field(default=FxEffectType.WOBBLE, init=False)
    c1: int
    c2: int
    c3: float
    c4: float
    c5: float
    c6: float
    c7: float


@dataclass(frozen=True, slots=True)
class BitCrusher:
    kind: FxEffectType = field(default=FxEffectType.BIT_CRUSHER, init=False)
    c1: float
    c2: int


@dataclass(frozen=True, slots=True)
class Echo:
    kind: FxEffectType = field(default=FxEffectType.ECHO, init=False)
    c1: int
    c2: float
    c3: float
    c4: float
    c5: float
    c6: float
    c7: float


@dataclass(frozen=True, slots=True)
class PitchShift:
    kind: FxEffectType = field(default=FxEffectType.PITCH_SHIFT, init=False)
    c1: float
    c2: float


@dataclass(frozen=True, slots=True)
class TapeStopEx:
    kind: FxEffectType = field(default=FxEffectType.TAPE_STOP_EX, init=False)
    c1: float
    c2: float
    c3: float
    c4: float
    c5: float


@dataclass(frozen=True, slots=True)
class LowPass:
    kind: FxEffectType = field(default=FxEffectType.LOW_PASS, init=False)
    c1: float
    c2: float
    c3: float
    c4: float


@dataclass(frozen=True, slots=True)
class HighPass:
    kind: FxEffectType = field(default=FxEffectType.HIGH_PASS, init=False)
    c1: float
    c2: float
    c3: float
    c4: float


@dataclass(frozen=True, slots=True)
class PitchAndSpeed:
    kind: FxEffectType = field(default=FxEffectType.PITCH_AND_SPEED, init=False)
    mix_percent: float
    pitch_semitones: float
    speed_multiplier: float


@dataclass(frozen=True, slots=True)
class LaserLowPass:
    kind: LaserEffectType = field(default=LaserEffectType.LOW_PASS, init=False)
    mix_percent: float
    lower_cutoff: float
    upper_cutoff: float
    resonance: float


@dataclass(frozen=True, slots=True)
class LaserHighPass:
    kind: LaserEffectType = field(default=LaserEffectType.HIGH_PASS, init=False)
    mix_percent: float
    lower_cutoff: float
    upper_cutoff: float
    resonance: float


@dataclass(frozen=True, slots=True)
class LaserBitCrusher:
    kind: LaserEffectType = field(default=LaserEffectType.BIT_CRUSHER, init=False)
    mix_percent: float
    reduction_factor: int


type FxEffect = (
    NoEffect
    | Retrigger
    | Gate
    | Flanger
    | TapeStop
    | SideChain
    | Wobble
    | BitCrusher
    | Echo
    | PitchShift
    | TapeStopEx
    | LowPass
    | HighPass
    | PitchAndSpeed
)
type LaserEffect = LaserLowPass | LaserHighPass | LaserBitCrusher


@dataclass(frozen=True, slots=True)
class EffectPair:
    first: FxEffect
    second: FxEffect


@dataclass(frozen=True, slots=True)
class ParameterAssignment:
    pair_index: int
    parameter: int = 0
    from_value: float = 0
    to_value: float = 0


def effect_columns(effect: FxEffect | LaserEffect) -> tuple[int | float, ...]:
    if isinstance(effect, NoEffect):
        return (effect.kind, effect.c1, effect.c2, effect.c3, effect.c4, effect.c5, effect.c6)
    if isinstance(effect, Retrigger):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
            effect.c6,
        )
    if isinstance(effect, Gate):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
        )
    if isinstance(effect, Flanger):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
        )
    if isinstance(effect, TapeStop):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
        )
    if isinstance(effect, SideChain):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
        )
    if isinstance(effect, Wobble):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
            effect.c6,
            effect.c7,
        )
    if isinstance(effect, BitCrusher):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
        )
    if isinstance(effect, Echo):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
            effect.c6,
            effect.c7,
        )
    if isinstance(effect, PitchShift):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
        )
    if isinstance(effect, TapeStopEx):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
            effect.c5,
        )
    if isinstance(effect, LowPass):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
        )
    if isinstance(effect, HighPass):
        return (
            effect.kind,
            effect.c1,
            effect.c2,
            effect.c3,
            effect.c4,
        )
    if isinstance(effect, PitchAndSpeed):
        return (
            effect.kind,
            effect.mix_percent,
            effect.pitch_semitones,
            effect.speed_multiplier,
        )
    if isinstance(effect, LaserLowPass):
        return (
            effect.kind,
            effect.mix_percent,
            effect.lower_cutoff,
            effect.upper_cutoff,
            effect.resonance,
        )
    if isinstance(effect, LaserHighPass):
        return (
            effect.kind,
            effect.mix_percent,
            effect.lower_cutoff,
            effect.upper_cutoff,
            effect.resonance,
        )
    if type(effect) is LaserBitCrusher:
        return (
            effect.kind,
            effect.mix_percent,
            effect.reduction_factor,
        )
    raise TypeError(f"Unknown effect model: {type(effect).__name__}")


FX_INTEGER_COLUMNS: dict[int, tuple[int, ...]] = {
    0: (1, 2, 3, 4, 5, 6),
    1: (1,),
    2: (2,),
    3: (4,),
    4: (),
    5: (
        3,
        4,
        5,
    ),
    6: (
        1,
        2,
    ),
    7: (2,),
    8: (1,),
    9: (),
    10: (),
    11: (),
    12: (),
    13: (),
}
