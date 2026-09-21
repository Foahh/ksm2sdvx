"""Neutral contracts for offline audio rendering."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue
from ksm2sdvx.resources.models import ProcessedResource


class RenderProgram(Protocol):
    """Immutable audio instructions; compiling a program performs no file access."""

    @property
    def sample_rate(self) -> int: ...

    @property
    def duration_frames(self) -> int: ...

    @property
    def offset_frames(self) -> int: ...

    @property
    def bgm_volume(self) -> float: ...

    def to_dict(self) -> dict[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class AudioSource:
    """A resolved file bound to an instruction's resource identifier."""

    id: str
    path: Path


@dataclass(frozen=True, slots=True)
class AudioRenderRequest:
    program: RenderProgram
    destination: Path
    source: AudioSource
    tracks: tuple[AudioSource, ...] = ()
    samples: tuple[AudioSource, ...] = ()


@dataclass(frozen=True, slots=True)
class AudioRenderResult:
    resource: ProcessedResource
    diagnostics: tuple[Diagnostic, ...] = ()
    versions: tuple[tuple[str, str], ...] = ()
    frames: int = 0
    effects: int = 0
    keysounds: int = 0

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "dependencies": dict(self.versions),
            "frames": self.frames,
            "sample_rate": 44100,
            "channels": 2,
            "effects": self.effects,
            "keysounds": self.keysounds,
            "diagnostics": tuple(d.to_dict() for d in self.diagnostics),
        }


class AudioRenderer(Protocol):
    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        """Write rendered PCM, or raise MusicError without publishing partial output."""
        ...
