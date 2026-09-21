"""Typed music processing inputs and outputs, independent of target formats."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.resources.models import ProcessedResource, ResourceRecord


@dataclass(frozen=True, slots=True)
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbtp: float


@dataclass(frozen=True, slots=True)
class S3vMusicSettings:
    """Audio timing uses KSON milliseconds; positive offsets trim the source.

    Preview intervals refer to the original file and bypass the chart offset.
    A supplied gain reuses the main track's gain for its preview. Authored source
    volume scales the normalization target, subject to the true-peak ceiling.
    """

    target_lufs: float = -11.0
    true_peak_dbtp: float = -1.0
    offset_ms: int = 0
    preview_start_ms: int | None = None
    preview_duration_ms: int | None = None
    gain_db: float | None = None
    source_volume: float = 1.0


@dataclass(frozen=True, slots=True)
class MusicRequest[SettingsT]:
    source: ResourceRecord
    destination: Path
    settings: SettingsT


@dataclass(frozen=True, slots=True)
class MusicResult:
    resource: ProcessedResource
    diagnostics: tuple[Diagnostic, ...] = ()
    measurement: LoudnessMeasurement | None = None
    gain_db: float | None = None
    output_measurement: LoudnessMeasurement | None = None
