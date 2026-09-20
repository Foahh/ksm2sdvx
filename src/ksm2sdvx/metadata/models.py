"""Per-chart metadata and typed target payloads."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue, Milliseconds


@dataclass(frozen=True, slots=True)
class MetadataField:
    json_pointer: str
    value: JsonValue


@dataclass(frozen=True, slots=True)
class ChartMetadata:
    source: Path
    title: str
    artist: str
    chart_author: str
    difficulty: int | str
    level: int
    display_bpm: str
    audio_offset: Milliseconds
    preview_offset: Milliseconds
    preview_duration: Milliseconds
    retained: tuple[MetadataField, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    """Separate metadata for every chart; no implicit shared-song values."""

    charts: tuple[ChartMetadata, ...]


@dataclass(frozen=True, slots=True)
class MetadataResult[TargetT]:
    metadata: TargetT
    diagnostics: tuple[Diagnostic, ...] = ()
