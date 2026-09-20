"""Contract for writing a composed package to its target representation."""

from pathlib import Path
from typing import Protocol

from ksm2sdvx.pipeline.models import PackageWriteResult, SdvxPackage


class PackageWriter[MetadataT](Protocol):
    def write(self, package: SdvxPackage[MetadataT], *, destination: Path) -> PackageWriteResult:
        """Write the complete package or raise Ksm2SdvxError; return actual written files."""
        ...
