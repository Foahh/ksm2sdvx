import json
import math
import shutil
import struct
import sys
import wave
import zlib
from dataclasses import replace
from pathlib import Path
from typing import cast
from xml.etree import ElementTree as ET

import pytest
from tests.conftest import document
from tests.support import chart_metadata, database_text, settings

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions, VoxChart
from ksm2sdvx.cli import main
from ksm2sdvx.common.errors import OutputError
from ksm2sdvx.metadata import MetadataError, PackageMetadata, SdvxMetadataConverter
from ksm2sdvx.pipeline import (
    LayeredFsPackageWriter,
    PackageChart,
    PackageError,
    SdvxPackage,
    build_package,
    load_package_config,
    parse_package_config,
)

MANIFEST = """name = "synthetic"
song_id = 3000

[[charts]]
path = "chart.kson"
slot = "exhaust"

[jacket]
source = "jacket.png"
author = "Synthetic artist"
"""


def _png(path: Path) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + b"\x80\x40\x20" * 2 + b"\0" + b"\x80\x40\x20" * 2))
        + chunk(b"IEND", b"")
    )


def _inputs(root: Path) -> tuple[Path, Path]:
    source = root / "source"
    source.mkdir()
    (source / "package.toml").write_text(MANIFEST, encoding="utf-8")
    (source / "chart.kson").write_text(
        document(
            audio={
                "bgm": {
                    "filename": "music.wav",
                    "offset": 100,
                    "preview": {"offset": 250, "duration": 1500},
                }
            }
        ),
        encoding="utf-8",
    )
    with wave.open(str(source / "music.wav"), "wb") as audio:
        audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        frames = b"".join(
            struct.pack("<hh", *(int(4000 * math.sin(2 * math.pi * 440 * n / 44100)),) * 2)
            for n in range(44100 * 3)
        )
        audio.writeframes(frames)
    _png(source / "jacket.png")
    data = root / "reference-data"
    (data / "others").mkdir(parents=True)
    (data / "graphics").mkdir()
    (data / "others/music_db.xml").write_text(database_text(), encoding="utf-8")
    # The package extends this existing archive by name; it does not read or copy its contents.
    (data / "graphics/s_jacket00.ifs").write_bytes(b"synthetic reference")
    return source / "package.toml", data


@pytest.mark.parametrize(
    "old,new",
    [
        ("song_id = 3000", "song_id = true"),
        ("song_id = 3000", "song_id = 3072"),
        ("song_id = 3000", "song_id = 10001"),
        ('slot = "exhaust"', 'slot = "unknown"'),
        ('path = "chart.kson"', 'path = "../chart.kson"'),
        ('name = "synthetic"', 'name = "../escape"'),
        ('name = "synthetic"', 'name = "synthetic"\nunknown = 1'),
        ('source = "jacket.png"', 'source = "../jacket.png"'),
        ('author = "Synthetic artist"', "author = 123"),
    ],
)
def test_manifest_rejects_invalid_configuration(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(PackageError):
        parse_package_config(MANIFEST.replace(old, new), base=tmp_path)


def test_manifest_paths_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "song"
    source.mkdir()
    manifest = source / "package.toml"
    manifest.write_text(
        MANIFEST.replace('slot = "exhaust"', 'slot = "exhaust"\nprice = -2\nlimited = 3')
        .replace('path = "chart.kson"', 'path = "charts/chart.kson"')
        .replace('source = "jacket.png"', 'source = "art/jacket.png"'),
        encoding="utf-8",
    )
    working_directory = tmp_path / "elsewhere"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    config = load_package_config(Path("../song/package.toml"))
    assert config.root == source
    assert config.charts[0].path == source / "charts/chart.kson"
    assert config.jacket.source == source / "art/jacket.png"
    assert config.jacket.author == "Synthetic artist"
    assert config.charts[0].price == -2 and config.charts[0].limited == 3
    assert config.target_lufs == -11


def test_per_chart_jacket_settings(tmp_path: Path) -> None:
    config = parse_package_config(
        MANIFEST.replace(
            "[jacket]",
            '[charts.jacket]\nsource = "special.png"\nauthor = "Other"\n\n[jacket]',
        ),
        base=tmp_path,
    )
    assert config.charts[0].jacket.source == tmp_path / "special.png"
    assert config.charts[0].jacket.author == "Other"
    assert config.jacket.source == tmp_path / "jacket.png"
    assert config.jacket.author == "Synthetic artist"


@pytest.mark.parametrize(
    "extra",
    [
        "[metadata]\ndistribution_date = 20260230",
        "[metadata]\ndistribution_date = true",
        "[metadata]\nbg_no = 65536",
        "[metadata]\ndemo_pri = -129",
        "[metadata]\ninf_ver = 256",
        "[charts.radar]\nnotes = -1",
        "[charts.radar]\npeak = 65536",
        "[charts.radar]\nhand_trip = true",
        "[charts.radar]\nunknown = 1",
    ],
)
def test_database_option_validation(tmp_path: Path, extra: str) -> None:
    with pytest.raises(PackageError):
        parse_package_config(MANIFEST + "\n" + extra, base=tmp_path)


def test_package_preflight_preserves_inputs_and_rejects_conflicts(tmp_path: Path) -> None:
    manifest, game = _inputs(tmp_path)
    config = load_package_config(manifest)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    output = tmp_path / "result"
    with pytest.raises(MetadataError) as error:
        build_package(
            replace(config, song_id=1),
            game_data=game,
            destination=output,
            options=ConversionOptions(),
            profile=DEFAULT_PROFILE,
        )
    assert "already exists" in str(error.value)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not output.exists()
    assert main(["package", str(manifest), "--game-data", str(game), "-o", str(game / "mod")]) == 1


@pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Package audio encoding requires Windows Media Format and FFmpeg",
)
def test_package_cli_produces_media_metadata_and_charts(tmp_path: Path) -> None:
    manifest, game = _inputs(tmp_path)
    source = manifest.parent
    (source / "advanced.kson").write_bytes((source / "chart.kson").read_bytes())
    manifest.write_text(
        MANIFEST.replace(
            'slot = "exhaust"',
            'slot = "exhaust"\njacket_print = -1\njacket_mask = 7\n'
            "[charts.radar]\nnotes = 11\npeak = 22\ntsumami = 33\ntricky = 44\nhand_trip = 55\none_hand = 66\n",
        ).replace(
            "[jacket]",
            '[[charts]]\npath = "advanced.kson"\nslot = "advanced"\n'
            '[charts.jacket]\nauthor = "Per-chart artist"\n\n[jacket]',
        )
        + "\n[metadata]\ndistribution_date = 20260102\nbg_no = 5\ngenre = 16\n"
        'is_fixed = 0\ndemo_pri = -2\ninf_ver = 4\nlicense_text = "Original & licensed"\n',
        encoding="utf-8",
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    output = tmp_path / "data_mods/synthetic"
    assert main(["package", str(manifest), "--game-data", str(game), "-o", str(output)]) == 0
    assert all(path.read_bytes() == content for path, content in before.items())
    expected_music = output / "music/3000_synthetic"
    assert (expected_music / "3000_synthetic_3e.vox").is_file()
    assert (expected_music / "3000_synthetic_2a.vox").is_file()
    assert (expected_music / "3000_synthetic.s3v").stat().st_size > 0
    assert (expected_music / "3000_synthetic_pre.s3v").stat().st_size > 0
    for suffix, size in (("", 300), ("_s", 108), ("_b", 676)):
        assert struct.unpack_from(
            ">II", (expected_music / f"jk_3000_3{suffix}.png").read_bytes(), 16
        ) == (size, size)
    selector = output / "graphics/s_jacket00_ifs/jk_3000_3_t.png"
    assert struct.unpack_from(">II", selector.read_bytes(), 16) == (128, 128)
    assert (output / "graphics/s_jacket00_ifs/jk_3000_2_t.png").is_file()
    entry = ET.fromstring((output / "others/music_db.merged.xml").read_bytes().decode("cp932"))
    song = entry.find("music")
    assert song is not None and song.get("id") == "3000"
    assert song.findtext("info/ascii") == "synthetic"
    assert song.findtext("info/volume") == "91"
    assert song.findtext("info/version") == "7"
    assert song.findtext("info/distribution_date") == "20260102"
    assert song.findtext("info/bg_no") == "5"
    assert song.findtext("info/genre") == "16"
    assert song.findtext("info/is_fixed") == "0"
    assert song.findtext("info/demo_pri") == "-2"
    assert song.findtext("info/inf_ver") == "4"
    assert song.findtext("info/license_text") == "Original & licensed"
    assert song.findtext("difficulty/exhaust/price") == "-1"
    assert song.findtext("difficulty/exhaust/limited") == "3"
    assert song.findtext("difficulty/exhaust/jacket_print") == "-1"
    assert song.findtext("difficulty/exhaust/jacket_mask") == "7"
    assert [node.text for node in song.findall("difficulty/exhaust/radar/*")] == [
        "11",
        "22",
        "33",
        "44",
        "55",
        "66",
    ]
    assert all(node.text == "0" for node in song.findall("difficulty/advanced/radar/*"))
    assert song.findtext("difficulty/exhaust/illustrator") == "Synthetic artist"
    assert song.findtext("difficulty/advanced/illustrator") == "Per-chart artist"
    report_text = (output / "ksm2sdvx-report.json").read_text(encoding="utf-8")
    report = cast(dict[str, object], json.loads(report_text))
    assert report["song_id"] == 3000
    music_report = cast(dict[str, object], report["music"])
    assert music_report["target_lufs"] == -11
    assert music_report["true_peak_dbtp"] == -1.0
    assert str(tmp_path) not in report_text and tmp_path.as_posix() not in report_text
    assert json.dumps(str(tmp_path))[1:-1] not in report_text
    assert main(["package", str(manifest), "--game-data", str(game), "-o", str(output)]) == 1


def test_package_strict_rejects_unconverted_metadata_before_output(tmp_path: Path) -> None:
    manifest, game = _inputs(tmp_path)
    chart = manifest.parent / "chart.kson"
    data = cast(dict[str, object], json.loads(chart.read_text(encoding="utf-8")))
    metadata = cast(dict[str, object], data["meta"])
    metadata["information"] = "A source-only annotation"
    chart.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "mod"
    with pytest.raises(PackageError, match="omit metadata"):
        build_package(
            load_package_config(manifest),
            game_data=game,
            destination=output,
            options=ConversionOptions(strict=True),
            profile=DEFAULT_PROFILE,
        )
    assert not output.exists()


def test_writer_rejects_traversal_and_leaves_existing_output(
    tmp_path: Path, vox_chart: VoxChart
) -> None:
    metadata = (
        SdvxMetadataConverter()
        .convert(PackageMetadata((chart_metadata(),)), settings=settings())
        .metadata
    )
    package = SdvxPackage(
        (PackageChart(Path("source.kson"), "../escape.vox", vox_chart),), metadata, ()
    )
    with pytest.raises(OutputError, match="Invalid package output path"):
        LayeredFsPackageWriter().write(package, destination=tmp_path / "mod")
    assert not (tmp_path / "mod").exists()
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep").write_bytes(b"original")
    with pytest.raises(OutputError, match="already exists"):
        LayeredFsPackageWriter().write(replace(package, charts=()), destination=output)
    assert (output / "keep").read_bytes() == b"original"
