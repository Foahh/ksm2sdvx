"""Immutable chart instructions for an offline audio renderer."""

from dataclasses import dataclass

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue
from ksm2sdvx.resources.models import ResourceReference


@dataclass(frozen=True, slots=True)
class AudioTempo:
    frame: int
    pulse: float
    bpm: float


@dataclass(frozen=True, slots=True)
class AudioEffect:
    name: str
    type: str
    bus: str
    parameters: tuple[tuple[str, str], ...]
    triggers: tuple[int, ...]
    builtin: bool


@dataclass(frozen=True, slots=True)
class AudioChange:
    frame: int
    bus: str
    effect: str
    parameter: str
    value: str


@dataclass(frozen=True, slots=True)
class AudioHold:
    start_frame: int
    end_frame: int
    lane: int


@dataclass(frozen=True, slots=True)
class AudioFxInvocation:
    start_frame: int
    end_frame: int
    lane: int
    hold_start_frame: int
    effect: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AudioLaserInvocation:
    frame: int
    effect: str | None


@dataclass(frozen=True, slots=True)
class AudioLaserPoint:
    frame: int
    pulse: float
    incoming: float
    outgoing: float
    curve_x: float
    curve_y: float


@dataclass(frozen=True, slots=True)
class AudioLaser:
    lane: int
    start_frame: int
    end_frame: int
    points: tuple[AudioLaserPoint, ...]


@dataclass(frozen=True, slots=True)
class AudioKeySound:
    frame: int
    lane: int
    resource_id: str
    volume: float
    pulse: int


@dataclass(frozen=True, slots=True)
class ChartAudioProgram:
    sample_rate: int
    duration_frames: int
    offset_frames: int
    bgm_volume: float
    tempos: tuple[AudioTempo, ...]
    effects: tuple[AudioEffect, ...]
    changes: tuple[AudioChange, ...]
    fx: tuple[AudioFxInvocation, ...]
    fx_holds: tuple[AudioHold, ...]
    laser_events: tuple[AudioLaserInvocation, ...]
    lasers: tuple[AudioLaser, ...]
    keysounds: tuple[AudioKeySound, ...]
    peaking_filter_delay_frames: int
    resources: tuple[ResourceReference, ...]
    coverage_paths: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    unsupported_paths: tuple[str, ...]
    key_sound_polyphony: int = 1

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "tempos": tuple(
                {"frame": e.frame, "pulse": e.pulse, "bpm": e.bpm} for e in self.tempos
            ),
            "effects": tuple(
                {
                    "name": e.name,
                    "type": e.type,
                    "bus": e.bus,
                    "parameters": dict(e.parameters),
                    "triggers": e.triggers,
                    "builtin": e.builtin,
                }
                for e in self.effects
            ),
            "changes": tuple(
                {
                    "frame": e.frame,
                    "bus": e.bus,
                    "effect": e.effect,
                    "parameter": e.parameter,
                    "value": e.value,
                }
                for e in self.changes
            ),
            "fx": tuple(
                {
                    "start_frame": e.start_frame,
                    "end_frame": e.end_frame,
                    "lane": e.lane,
                    "hold_start_frame": e.hold_start_frame,
                    "effect": e.effect,
                    "parameters": dict(e.parameters),
                }
                for e in self.fx
            ),
            "fx_holds": tuple(
                {"start_frame": e.start_frame, "end_frame": e.end_frame, "lane": e.lane}
                for e in self.fx_holds
            ),
            "laser_events": tuple(
                {"frame": e.frame, "effect": e.effect} for e in self.laser_events
            ),
            "lasers": tuple(
                {
                    "lane": e.lane,
                    "start_frame": e.start_frame,
                    "end_frame": e.end_frame,
                    "points": tuple(
                        {
                            "frame": p.frame,
                            "pulse": p.pulse,
                            "incoming": p.incoming,
                            "outgoing": p.outgoing,
                            "curve_x": p.curve_x,
                            "curve_y": p.curve_y,
                        }
                        for p in e.points
                    ),
                }
                for e in self.lasers
            ),
            "keysounds": tuple(
                {"frame": e.frame, "lane": e.lane, "resource_id": e.resource_id, "volume": e.volume}
                for e in self.keysounds
            ),
            "peaking_filter_delay_frames": self.peaking_filter_delay_frames,
            "key_sound_polyphony": self.key_sound_polyphony,
        }
