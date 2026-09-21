"""Structured diagnostics shared by all stages."""

from dataclasses import dataclass
from enum import StrEnum

from ksm2sdvx.common.types import JsonValue


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Stage(StrEnum):
    PARSE = "parse"
    CONVERT = "convert"
    INSPECT = "inspect"
    MUSIC = "music"
    JACKET = "jacket"
    METADATA = "metadata"
    PACKAGE = "package"


class FeatureStatus(StrEnum):
    CONVERTED = "converted"
    APPROXIMATED = "approximated"
    DEFERRED = "deferred"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    stage: Stage
    message: str
    feature: str
    json_pointer: str = ""
    pulse: int | None = None
    source_path: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "stage": self.stage.value,
            "message": self.message,
            "feature": self.feature,
            "json_pointer": self.json_pointer,
            "pulse": self.pulse,
            "source_path": self.source_path,
        }


@dataclass(frozen=True, slots=True)
class FeatureResult:
    feature: str
    status: FeatureStatus
    json_pointer: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "feature": self.feature,
            "status": self.status.value,
            "json_pointer": self.json_pointer,
        }
