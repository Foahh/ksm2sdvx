from dataclasses import replace
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from tests.support import chart_metadata, settings

from ksm2sdvx.metadata import (
    ChartAssignment,
    ChartRadar,
    ChartSlot,
    MetadataError,
    MetadataField,
    PackageMetadata,
    SdvxMetadataConverter,
    serialize_music_database,
)


def test_new_song_fragment_fields_slots_encoding_and_names() -> None:
    source = PackageMetadata((chart_metadata(),))
    configuration = replace(settings(), distribution_date=date(2026, 1, 2))
    result = SdvxMetadataConverter().convert(source, settings=configuration)
    payload = result.metadata
    encoded = serialize_music_database(payload)
    assert encoded.startswith(b'<?xml version="1.0" encoding="shift-jis"?>\n')
    assert b"\r" not in encoded
    fragment = ET.fromstring(encoded.decode("cp932"))
    assert fragment.tag == "mdb" and fragment.attrib == {}
    assert [entry.get("id") for entry in fragment] == ["3000"]
    assert fragment.findtext("music/info/title_name") == source.charts[0].title
    assert fragment.findtext("music/info/title_yomigana") == source.charts[0].title
    assert fragment.findtext("music/info/bpm_min") == "12345"
    assert fragment.findtext("music/info/license_text") is None
    assert fragment.findtext("music/info/bg_no") == "2"
    assert fragment.findtext("music/info/distribution_date") == "20260102"
    assert fragment.findtext("music/info/genre") == "0"
    assert fragment.findtext("music/info/version") == "7"
    assert fragment.findtext("music/info/volume") == "91"
    assert fragment.findtext("music/difficulty/exhaust/difnum") == "150"
    assert fragment.findtext("music/difficulty/exhaust/effected_by") == "Charter"
    assert fragment.findtext("music/difficulty/exhaust/illustrator") == "Illustrator"
    assert fragment.findtext("music/difficulty/exhaust/max_exscore") == "0"
    assert fragment.findtext("music/difficulty/exhaust/limited") == "3"
    assert fragment.findtext("music/difficulty/exhaust/price") == "-1"
    assert fragment.findtext("music/difficulty/exhaust/jacket_print") == "-2"
    assert fragment.findtext("music/difficulty/exhaust/jacket_mask") == "0"
    assert fragment.findtext("music/difficulty/novice/difnum") == "0"
    assert all(node.text == "0" for node in fragment.findall("music/difficulty/*/radar/*"))
    level = fragment.find("music/difficulty/exhaust/difnum")
    assert level is not None and level.attrib == {"__type": "u8"}
    assert payload.stem == "3000_new_song"
    assert payload.directory.as_posix() == "music/3000_new_song"
    assert payload.chart_filename(ChartSlot.EXHAUST) == "3000_new_song_3e.vox"
    assert payload.chart_filename(ChartSlot.ULTIMATE) == "3000_new_song_6u.vox"
    assert payload.music_filename(slot=ChartSlot.EXHAUST) == "3000_new_song_3e.s3v"
    assert payload.music_filename(preview=True) == "3000_new_song_pre.s3v"
    assert payload.jacket_filename(ChartSlot.EXHAUST) == "jk_3000_3.png"
    assert payload.jacket_filename(ChartSlot.MAXIMUM, "big") == "jk_3000_5_b.png"
    assert payload.jacket_filename(ChartSlot.ULTIMATE, "small") == "jk_3000_6_s.png"
    assert not result.diagnostics
    assert source.charts[0].audio_offset == 120


def test_explicit_shared_values_and_per_chart_values() -> None:
    first = chart_metadata()
    second = replace(
        chart_metadata("second.kson"), title="Different", level=18, chart_author="Other"
    )
    configuration = replace(
        settings(),
        title="Shared title",
        title_yomigana="SHARED",
        bpm_min=100,
        bpm_max=150,
        volume=90,
        version=6,
        charts=(
            ChartAssignment(first.source, ChartSlot.EXHAUST, max_exscore=1000, price=-2, limited=3),
            ChartAssignment(second.source, ChartSlot.MAXIMUM, level_tenths=185, max_exscore=2000),
        ),
    )
    result = SdvxMetadataConverter().convert(
        PackageMetadata((first, second)), settings=configuration
    )
    xml = ET.fromstring(serialize_music_database(result.metadata).decode("cp932"))
    assert xml.findtext("music/info/title_name") == "Shared title"
    assert xml.findtext("music/info/title_yomigana") == "SHARED"
    assert xml.findtext("music/info/bpm_max") == "15000"
    assert xml.findtext("music/difficulty/maximum/difnum") == "185"
    assert xml.findtext("music/difficulty/maximum/effected_by") == "Other"
    assert xml.findtext("music/difficulty/exhaust/max_exscore") == "1000"
    assert xml.findtext("music/difficulty/exhaust/price") == "-2"
    assert xml.findtext("music/difficulty/exhaust/limited") == "3"
    assert result.metadata.volume == 90 and result.metadata.version == 6


def test_database_controls_and_complete_radar_are_serialized() -> None:
    configuration = replace(
        settings(),
        distribution_date=date(2026, 1, 2),
        bg_no=5,
        genre=16,
        is_fixed=0,
        demo_pri=-2,
        inf_ver=4,
        license_text="Original & licensed",
        charts=(
            replace(
                settings().charts[0],
                jacket_print=-1,
                jacket_mask=7,
                radar=ChartRadar(10, 20, 30, 40, 50, 65535),
            ),
        ),
    )
    result = SdvxMetadataConverter().convert(
        PackageMetadata((chart_metadata(),)), settings=configuration
    )
    xml = ET.fromstring(serialize_music_database(result.metadata).decode("cp932"))
    for name, value, kind in (
        ("distribution_date", "20260102", "u32"),
        ("bg_no", "5", "u16"),
        ("genre", "16", "u32"),
        ("is_fixed", "0", "u8"),
        ("demo_pri", "-2", "s8"),
        ("inf_ver", "4", "u8"),
    ):
        node = xml.find(f"music/info/{name}")
        assert node is not None and node.text == value and node.attrib == {"__type": kind}
    assert xml.findtext("music/info/license_text") == "Original & licensed"
    assert xml.findtext("music/difficulty/exhaust/jacket_print") == "-1"
    assert xml.findtext("music/difficulty/exhaust/jacket_mask") == "7"
    assert [
        (node.tag, node.text, node.get("__type"))
        for node in xml.findall("music/difficulty/exhaust/radar/*")
    ] == [
        ("notes", "10", "u16"),
        ("peak", "20", "u16"),
        ("tsumami", "30", "u16"),
        ("tricky", "40", "u16"),
        ("hand-trip", "50", "u16"),
        ("one-hand", "65535", "u16"),
    ]
    assert all(node.text == "0" for node in xml.findall("music/difficulty/novice/radar/*"))


@pytest.mark.parametrize("radar", [ChartRadar(notes=12), ChartRadar(0, 0, 0, 0, 0, 0)])
def test_radar_defaults_only_unspecified_axes(radar: ChartRadar) -> None:
    configuration = replace(settings(), charts=(replace(settings().charts[0], radar=radar),))
    result = SdvxMetadataConverter().convert(
        PackageMetadata((chart_metadata(),)), settings=configuration
    )
    values = result.metadata.entry.child("difficulty").child("exhaust").child("radar")
    assert values.child("notes").text == str(radar.notes)
    assert values.child("peak").text == "0"


@pytest.mark.parametrize("value", [-1, 65536, True])
def test_radar_storage_range(value: int) -> None:
    configuration = replace(
        settings(), charts=(replace(settings().charts[0], radar=ChartRadar(notes=value)),)
    )
    with pytest.raises(MetadataError, match="radar.notes"):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)), settings=configuration
        )


@pytest.mark.parametrize(
    "name,value",
    [
        ("bg_no", 65536),
        ("genre", 2**32),
        ("is_fixed", 256),
        ("demo_pri", -129),
        ("demo_pri", 128),
        ("inf_ver", 256),
    ],
)
def test_song_control_storage_ranges(name: str, value: int) -> None:
    with pytest.raises(MetadataError, match=name):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)),
            settings=replace(settings(), **{name: value}),
        )


@pytest.mark.parametrize("name,value", [("jacket_print", -(2**31) - 1), ("jacket_mask", 2**31)])
def test_jacket_control_storage_ranges(name: str, value: int) -> None:
    configuration = replace(settings(), charts=(replace(settings().charts[0], **{name: value}),))
    with pytest.raises(MetadataError, match=name):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)), settings=configuration
        )


@pytest.mark.parametrize(
    "ascii_name", [None, "../song", "bad/name", "song.wav:stream", "日本語", ""]
)
def test_invalid_target_names(ascii_name: str | None) -> None:
    with pytest.raises(MetadataError, match="ascii_name"):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)),
            settings=replace(settings(), ascii_name=ascii_name),
        )


def test_assignment_errors() -> None:
    source = PackageMetadata((chart_metadata(),))
    converter = SdvxMetadataConverter()
    for configuration, message in (
        (replace(settings(), charts=()), "At least one"),
        (replace(settings(), charts=settings().charts * 2), "assigned exactly once"),
        (
            replace(settings(), charts=(ChartAssignment(Path("other.kson"), ChartSlot.EXHAUST),)),
            "cover exactly",
        ),
    ):
        with pytest.raises(MetadataError, match=message):
            converter.convert(source, settings=configuration)


def test_conflicting_metadata_and_nonrepresentable_values() -> None:
    first, second = chart_metadata(), replace(chart_metadata("second.kson"), title="Different")
    configuration = replace(
        settings(),
        charts=(
            ChartAssignment(first.source, ChartSlot.EXHAUST),
            ChartAssignment(second.source, ChartSlot.MAXIMUM),
        ),
    )
    with pytest.raises(MetadataError, match="different title"):
        SdvxMetadataConverter().convert(PackageMetadata((first, second)), settings=configuration)
    for title in ("Song 😀", "Song\x00"):
        with pytest.raises(MetadataError, match="Shift-JIS"):
            SdvxMetadataConverter().convert(
                PackageMetadata((first,)),
                settings=replace(settings(), title=title),
            )


@pytest.mark.parametrize(
    "minimum,maximum", [(120.123, 130), (float("nan"), 130), (130, 120), (0, 120)]
)
def test_unrepresentable_bpm(minimum: float, maximum: float) -> None:
    with pytest.raises(MetadataError):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)),
            settings=replace(settings(), bpm_min=minimum, bpm_max=maximum),
        )


@pytest.mark.parametrize("song_id", [0, -1, 3072, 9001, 10001, 32768, True])
def test_song_id_must_fit_target_song_tables(song_id: int) -> None:
    with pytest.raises(MetadataError, match="song_id"):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)),
            settings=replace(settings(), song_id=song_id),
        )


@pytest.mark.parametrize("song_id", [1, 3071])
def test_supported_song_id_boundaries(song_id: int) -> None:
    result = SdvxMetadataConverter().convert(
        PackageMetadata((chart_metadata(),)), settings=replace(settings(), song_id=song_id)
    )
    assert result.metadata.song_id == song_id
    assert result.metadata.stem == f"{song_id:04}_new_song"


@pytest.mark.parametrize("price,limited", [(-(2**31) - 1, 0), (2**31, 0), (0, -1), (0, 256)])
def test_access_setting_storage_ranges(price: int, limited: int) -> None:
    assignment = replace(settings().charts[0], price=price, limited=limited)
    with pytest.raises(MetadataError, match="price|limited"):
        SdvxMetadataConverter().convert(
            PackageMetadata((chart_metadata(),)),
            settings=replace(settings(), charts=(assignment,)),
        )


@pytest.mark.parametrize("slot", list(ChartSlot))
def test_new_entry_needs_no_existing_song_and_reads_source_jacket_author(slot: ChartSlot) -> None:
    source = replace(
        chart_metadata(), retained=(MetadataField("/meta/jacket_author", "KSON artwork author"),)
    )
    configuration = replace(
        settings(),
        charts=(ChartAssignment(source.source, slot),),
    )
    result = SdvxMetadataConverter().convert(PackageMetadata((source,)), settings=configuration)
    difficulty = result.metadata.entry.child("difficulty")
    assert difficulty.child(slot.value).child("illustrator").text == "KSON artwork author"
    assert len(difficulty.children) == len(ChartSlot)
    assert result.metadata.entry.child("info").child("inf_ver").text == (
        "2" if slot is ChartSlot.INFINITE else "0"
    )
    overridden = SdvxMetadataConverter().convert(
        PackageMetadata((source,)),
        settings=replace(configuration, charts=(ChartAssignment(source.source, slot, "Override"),)),
    )
    assert (
        overridden.metadata.entry.child("difficulty").child(slot.value).child("illustrator").text
        == "Override"
    )
