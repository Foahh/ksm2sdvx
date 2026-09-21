"""Synthetic metadata inputs shared by component and package tests."""

from pathlib import Path

from ksm2sdvx.common.types import Milliseconds
from ksm2sdvx.metadata import (
    ChartAssignment,
    ChartMetadata,
    ChartSlot,
    SdvxMetadataSettings,
)


def chart_metadata(name: str = "chart.kson") -> ChartMetadata:
    return ChartMetadata(
        Path(name),
        "新曲 & Test",
        "Artist",
        "Charter",
        "custom",
        15,
        "123.45",
        Milliseconds(120),
        Milliseconds(1000),
        Milliseconds(15000),
    )


def settings() -> SdvxMetadataSettings:
    return SdvxMetadataSettings(
        3000,
        (ChartAssignment(Path("chart.kson"), ChartSlot.EXHAUST, "Illustrator"),),
        ascii_name="new_song",
    )
