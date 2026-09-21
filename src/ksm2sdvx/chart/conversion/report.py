from collections.abc import Mapping
from dataclasses import dataclass

from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.types import KsonPulse
from ksm2sdvx.common.diagnostics import Diagnostic, FeatureResult, FeatureStatus, Severity, Stage
from ksm2sdvx.common.types import JsonValue


def summarize_audio_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> tuple[Diagnostic, ...]:
    """Summarize standalone rendering requirements without per-event warning spam."""
    rendering_codes = {
        "UNSUPPORTED_EFFECT_DEFINITION",
        "UNSUPPORTED_EFFECT_EVENT",
        "UNSUPPORTED_EFFECT_PARAMETER",
        "UNSUPPORTED_KEYSOUND",
    }
    requires_rendering = tuple(d for d in diagnostics if d.code in rendering_codes)
    if not requires_rendering:
        return diagnostics
    return tuple(d for d in diagnostics if d.code not in rendering_codes) + (
        Diagnostic(
            "AUDIO_RENDERING_REQUIRED",
            Severity.WARNING,
            Stage.CONVERT,
            "Authored effects or keysounds are absent from chart-only output; "
            "use package conversion to render supported audio.",
            "audio",
            "/audio",
        ),
    )


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
