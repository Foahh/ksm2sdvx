"""Source references, discovered resources, and processed file references."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic


@dataclass(frozen=True, slots=True)
class ResourceReference:
    name: str
    role: str
    path: str
    preset: bool = False


@dataclass(frozen=True, slots=True)
class ResourceUse:
    source: Path
    role: str
    json_pointer: str


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    name: str
    resolved_path: Path | None
    preset: bool
    exists: bool
    uses: tuple[ResourceUse, ...]


@dataclass(frozen=True, slots=True)
class ResourceInput:
    owner: Path
    reference: ResourceReference


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    assets: tuple[ResourceRecord, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class ProcessedResource:
    """An output file and the source uses it satisfies; construction does no I/O."""

    path: Path
    uses: tuple[ResourceUse, ...]
