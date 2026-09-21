"""Synthetic metadata inputs shared by component and package tests."""

from pathlib import Path
from xml.etree import ElementTree as ET

from ksm2sdvx.common.types import Milliseconds
from ksm2sdvx.metadata import (
    ChartAssignment,
    ChartMetadata,
    ChartSlot,
    SdvxMetadataSettings,
    parse_music_database,
)


def database_text() -> str:
    root = ET.Element("mdb", {"revision": "fixture"})
    entry = ET.SubElement(root, "music", {"id": "1"})
    info = ET.SubElement(entry, "info")
    for name, value, kind in (
        ("title_name", "Existing song", ""),
        ("title_yomigana", "Existing reading", ""),
        ("artist_name", "Existing artist", ""),
        ("artist_yomigana", "Existing artist reading", ""),
        ("ascii", "existing", ""),
        ("bpm_min", "12000", "u32"),
        ("bpm_max", "12000", "u32"),
        ("volume", "91", "u16"),
        ("version", "4", "u8"),
        ("license_text", "Existing license", ""),
        ("bg_no", "1", "u16"),
    ):
        ET.SubElement(info, name, {"__type": kind} if kind else {}).text = value
    difficulty = ET.SubElement(entry, "difficulty")
    for slot in (ChartSlot.NOVICE, ChartSlot.ADVANCED, ChartSlot.EXHAUST, ChartSlot.MAXIMUM):
        chart = ET.SubElement(difficulty, slot.value)
        for name, value, kind in (
            ("difnum", "100", "u8"),
            ("effected_by", "Existing author", ""),
            ("illustrator", "Existing artist", ""),
            ("max_exscore", "1234", "s32"),
            ("limited", "1", "u8"),
            ("price", "-1", "s32"),
        ):
            ET.SubElement(chart, name, {"__type": kind} if kind else {}).text = value
        radar = ET.SubElement(chart, "radar")
        for name in ("notes", "peak", "tsumami", "tricky", "hand-trip", "one-hand"):
            ET.SubElement(radar, name, {"__type": "u16"}).text = "42"
    return ET.tostring(root, encoding="unicode")


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
        parse_music_database(database_text()),
        3000,
        (ChartAssignment(Path("chart.kson"), ChartSlot.EXHAUST, "Illustrator"),),
        ascii_name="new_song",
    )
