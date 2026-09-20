"""Typed music processing inputs and outputs, independent of target formats."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.resources.models import ProcessedResource, ResourceRecord


@dataclass(frozen=True, slots=True)
class MusicRequest[SettingsT]:
    source: ResourceRecord
    destination: Path
    settings: SettingsT


@dataclass(frozen=True, slots=True)
class MusicResult:
    resource: ProcessedResource
    diagnostics: tuple[Diagnostic, ...] = ()
