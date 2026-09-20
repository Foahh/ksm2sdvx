from collections.abc import Mapping
from dataclasses import dataclass

from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.types import KsonPulse
from ksm2sdvx.common.diagnostics import Diagnostic, FeatureResult, FeatureStatus, Severity, Stage
from ksm2sdvx.common.types import JsonValue


@dataclass(frozen=True, slots=True)
class ConversionReport:
    profile: str
    options: ConversionOptions
    end_pulse: KsonPulse
    counts: Mapping[str, int]
    diagnostics: tuple[Diagnostic, ...]
    features: tuple[FeatureResult, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "kson_format_version": 1,
            "vox_version": 13,
            "profile": self.profile,
            "options": self.options.to_dict(),
            "end_pulse": self.end_pulse,
            "counts": dict(self.counts),
            "diagnostics": tuple(d.to_dict() for d in self.diagnostics),
            "features": tuple(f.to_dict() for f in self.features),
        }


class ReportBuilder:
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.features: list[FeatureResult] = []
        self.counts: dict[str, int] = {}

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def record(
        self,
        feature: str,
        status: FeatureStatus,
        path: str,
        *,
        code: str = "",
        message: str = "",
        pulse: KsonPulse | None = None,
    ) -> None:
        self.features.append(FeatureResult(feature, status, path))
        if code:
            self.diagnostics.append(
                Diagnostic(
                    code,
                    Severity.WARNING
                    if status in (FeatureStatus.UNSUPPORTED, FeatureStatus.APPROXIMATED)
                    else Severity.INFO,
                    Stage.CONVERT,
                    message,
                    feature,
                    path,
                    pulse,
                )
            )
