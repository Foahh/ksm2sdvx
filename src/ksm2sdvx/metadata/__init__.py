"""Public metadata models, database conversion, and conversion contract."""

from ksm2sdvx.metadata.converter import SdvxMetadataConverter, serialize_music_database
from ksm2sdvx.metadata.database import MusicDatabase, load_music_database, parse_music_database
from ksm2sdvx.metadata.errors import MetadataError
from ksm2sdvx.metadata.interfaces import MetadataConverter
from ksm2sdvx.metadata.models import (
    ChartAssignment,
    ChartMetadata,
    ChartRadar,
    ChartSlot,
    MetadataField,
    MetadataResult,
    PackageMetadata,
    SdvxMetadata,
    SdvxMetadataSettings,
)

__all__ = [
    "ChartAssignment",
    "ChartMetadata",
    "ChartRadar",
    "ChartSlot",
    "MetadataConverter",
    "MetadataError",
    "MetadataField",
    "MetadataResult",
    "MusicDatabase",
    "PackageMetadata",
    "SdvxMetadata",
    "SdvxMetadataConverter",
    "SdvxMetadataSettings",
    "load_music_database",
    "parse_music_database",
    "serialize_music_database",
]
