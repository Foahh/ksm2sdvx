"""Package inputs, inspection results, and composed output models."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.chart import ConversionResult, KsonChart, VoxChart
from ksm2sdvx.common.diagnostics import Diagnostic, Severity
from ksm2sdvx.resources.models import ProcessedResource, ResourceRecord


@dataclass(frozen=True, slots=True)
class SourcePackage:
    root: Path
    charts: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class InspectedChart:
    source_path: Path
    output_name: str
    source: KsonChart
    conversion: ConversionResult
    parse_diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class PackageInspection:
    root: Path
    charts: tuple[InspectedChart, ...]
    assets: tuple[ResourceRecord, ...]
    diagnostics: tuple[Diagnostic, ...]
    schema_version: int = 2

    @property
    def valid(self) -> bool:
        return not any(d.severity == Severity.ERROR for d in self.diagnostics)


@dataclass(frozen=True, slots=True)
class PackageChart:
    source_path: Path
    output_name: str
    chart: VoxChart


@dataclass(frozen=True, slots=True)
class SdvxPackage[MetadataT]:
    """Composed chart data, target metadata, and processed file references."""

    charts: tuple[PackageChart, ...]
    metadata: MetadataT
    resources: tuple[ProcessedResource, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageWriteResult:
    destination: Path
    files: tuple[Path, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
