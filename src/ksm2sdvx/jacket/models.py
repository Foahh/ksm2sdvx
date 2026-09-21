"""Typed jacket requests, outputs, and arcade image settings."""

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.jacket.errors import JacketError
from ksm2sdvx.resources.models import ProcessedResource, ResourceRecord


class JacketSize(IntEnum):
    SMALL = 108
    SELECTOR = 128
    STANDARD = 300
    LARGE = 676


@dataclass(frozen=True, slots=True)
class JacketSettings:
    """Square RGB output; transparent pixels and containment margins use black."""

    size: JacketSize = JacketSize.STANDARD

    def __post_init__(self) -> None:
        if type(self.size) is not JacketSize:
            raise JacketError("Jacket size must be a JacketSize value.")


@dataclass(frozen=True, slots=True)
class JacketRequest[SettingsT]:
    source: ResourceRecord
    destination: Path
    settings: SettingsT


@dataclass(frozen=True, slots=True)
class JacketResult:
    resource: ProcessedResource
    diagnostics: tuple[Diagnostic, ...] = ()
