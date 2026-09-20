"""Contract for converting source metadata to a defined target representation."""

from typing import Protocol

from ksm2sdvx.metadata.models import MetadataResult, PackageMetadata


class MetadataConverter[SettingsT, TargetT](Protocol):
    def convert(self, source: PackageMetadata, *, settings: SettingsT) -> MetadataResult[TargetT]:
        """Convert every chart's metadata or raise Ksm2SdvxError."""
        ...
