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
from tests.audio_support import SilentS3vEncoder
from tests.conftest import document
from tests.support import chart_metadata, settings

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions, VoxChart
from ksm2sdvx.chart.conversion.converter import UnsupportedFeaturesError
from ksm2sdvx.cli import main
from ksm2sdvx.common.errors import OutputError
from ksm2sdvx.jacket import FfmpegJacketProcessor, JacketRequest, JacketResult, JacketSettings
from ksm2sdvx.metadata import PackageMetadata, SdvxMetadataConverter
from ksm2sdvx.music import (
    FfmpegMusicProcessor,
    MusicError,
    MusicRequest,
    MusicResult,
    S3vMusicSettings,
)
from ksm2sdvx.music.render_models import AudioRenderRequest, AudioRenderResult
from ksm2sdvx.pipeline import (
    LayeredFsPackageWriter,
    PackageChart,
    PackageError,
    SdvxPackage,
    build_package,
    load_package_config,
    parse_package_config,
)
from ksm2sdvx.resources.models import ProcessedResource

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


def _inputs(root: Path) -> Path:
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
    return source / "package.toml"


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


@pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Package audio encoding requires Windows Media Format and FFmpeg",
)
def test_package_cli_produces_media_metadata_and_charts(tmp_path: Path) -> None:
    manifest = _inputs(tmp_path)
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
    assert main(["package", str(manifest), "-o", str(output)]) == 0
    assert all(path.read_bytes() == content for path, content in before.items())
    expected_music = output / "music/3000_synthetic"
    assert (expected_music / "3000_synthetic_3e.vox").is_file()
    assert (expected_music / "3000_synthetic_2a.vox").is_file()
    assert (expected_music / "3000_synthetic_3e.s3v").stat().st_size > 0
    assert (expected_music / "3000_synthetic_2a.s3v").stat().st_size > 0
    assert not (expected_music / "3000_synthetic.s3v").exists()
    assert (expected_music / "3000_synthetic_pre.s3v").stat().st_size > 0
    for audio in expected_music.glob("*.s3v"):
        data = audio.read_bytes()
        assert struct.unpack("<4sII", data[-32:-20]) == (b"S3V0", 32, len(data) - 32)
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
    chart_audio = cast(list[dict[str, object]], music_report["charts"])
    assert [item["slot"] for item in chart_audio] == ["exhaust", "advanced"]
    preview_report = cast(dict[str, object], music_report["preview"])
    assert preview_report["reference"] == "original_full_track"
    assert str(tmp_path) not in report_text and tmp_path.as_posix() not in report_text
    assert json.dumps(str(tmp_path))[1:-1] not in report_text
    assert main(["package", str(manifest), "-o", str(output)]) == 1


def test_package_strict_rejects_unconverted_metadata_before_output(tmp_path: Path) -> None:
    manifest = _inputs(tmp_path)
    chart = manifest.parent / "chart.kson"
    data = cast(dict[str, object], json.loads(chart.read_text(encoding="utf-8")))
    metadata = cast(dict[str, object], data["meta"])
    metadata["std_bpm"] = 150
    chart.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "mod"
    with pytest.raises(PackageError, match="omit metadata"):
        build_package(
            load_package_config(manifest),
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


class _PackageMusic(FfmpegMusicProcessor):
    def __init__(self) -> None:
        super().__init__(encoder=SilentS3vEncoder())
        self.full: list[MusicRequest[S3vMusicSettings]] = []
        self.previews: list[MusicRequest[S3vMusicSettings]] = []

    def process(self, request: MusicRequest[S3vMusicSettings]) -> MusicResult:
        self.full.append(request)
        source = request.source.resolved_path
        assert source is not None
        request.destination.write_bytes(source.read_bytes())
        return MusicResult(
            ProcessedResource(request.destination, ()), gain_db=float(len(self.full))
        )

    def process_preview(self, request: MusicRequest[S3vMusicSettings]) -> MusicResult:
        self.previews.append(request)
        request.destination.write_bytes(b"original preview")
        return MusicResult(ProcessedResource(request.destination, ()), gain_db=3.0)


class _PackageJackets(FfmpegJacketProcessor):
    def process(self, request: JacketRequest[JacketSettings]) -> JacketResult:
        request.destination.write_bytes(b"converted jacket")
        return JacketResult(ProcessedResource(request.destination, ()))


class _PackageRenderer:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.requests: list[AudioRenderRequest] = []
        self.fail_after = fail_after

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        self.requests.append(request)
        request.destination.write_bytes(f"chart audio {len(self.requests)}".encode())
        if self.fail_after is not None and len(self.requests) > self.fail_after:
            raise MusicError("Renderer failed")
        return AudioRenderResult(ProcessedResource(request.destination, ()), frames=44100)


def _stub_package_media(monkeypatch: pytest.MonkeyPatch) -> _PackageMusic:
    music = _PackageMusic()

    def make_music(ffmpeg: str) -> FfmpegMusicProcessor:
        return music

    monkeypatch.setattr("ksm2sdvx.pipeline.build.FfmpegMusicProcessor", make_music)
    monkeypatch.setattr("ksm2sdvx.pipeline.build.FfmpegJacketProcessor", _PackageJackets)
    return music


def test_package_ignores_source_presentation_and_reports_metadata_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _inputs(tmp_path)
    chart = manifest.parent / "chart.kson"
    data = cast(dict[str, object], json.loads(chart.read_text(encoding="utf-8")))
    metadata = cast(dict[str, object], data["meta"])
    metadata.update(
        information="Source-only annotation",
        title_img_filename="missing-title.png",
        artist_img_filename="../missing-artist.png",
        icon_filename="missing-icon.png",
    )
    data["bg"] = {"movie": {"filename": "../unused-movie.mp4"}}
    chart.write_text(json.dumps(data), encoding="utf-8")
    _stub_package_media(monkeypatch)
    output = tmp_path / "mod"
    result = build_package(
        load_package_config(manifest),
        destination=output,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
        renderer=_PackageRenderer(),
    )
    assert not result.diagnostics
    report = cast(dict[str, object], json.loads((output / "ksm2sdvx-report.json").read_text()))
    defaults = cast(dict[str, object], report["metadata"])["defaulted_fields"]
    assert defaults == [
        f"difficulty/exhaust/{field}"
        for field in (
            "radar/notes",
            "radar/peak",
            "radar/tsumami",
            "radar/tricky",
            "radar/hand-trip",
            "radar/one-hand",
            "max_exscore",
        )
    ]
    assert not any("missing" in path.name or "movie" in path.name for path in result.files)


@pytest.mark.parametrize("with_jacket", [False, True])
@pytest.mark.parametrize("strict", [False, True])
def test_package_allows_charts_without_jackets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_jacket: bool, strict: bool
) -> None:
    manifest = _inputs(tmp_path)
    source = manifest.parent
    text = MANIFEST.split("[jacket]")[0]
    if with_jacket:
        (source / "advanced.kson").write_bytes((source / "chart.kson").read_bytes())
        text += (
            '[[charts]]\npath = "advanced.kson"\nslot = "advanced"\n'
            '[charts.jacket]\nsource = "jacket.png"\n'
        )
    else:
        (source / "jacket.png").unlink()
    manifest.write_text(text, encoding="utf-8")
    _stub_package_media(monkeypatch)
    output = tmp_path / "mod"
    build_package(
        load_package_config(manifest),
        destination=output,
        options=ConversionOptions(strict=strict),
        profile=DEFAULT_PROFILE,
        renderer=_PackageRenderer(),
    )
    folder = output / "music/3000_synthetic"
    assert (folder / "3000_synthetic_3e.vox").is_file()
    assert (folder / "3000_synthetic_3e.s3v").is_file()
    assert (folder / "3000_synthetic_pre.s3v").is_file()
    assert not list(output.rglob("jk_3000_3*.png"))
    if with_jacket:
        assert len(list(output.rglob("jk_3000_2*.png"))) == 4
    else:
        assert not list(output.rglob("*.png"))
        assert not (output / "graphics").exists()
    xml = ET.fromstring((output / "others/music_db.merged.xml").read_bytes().decode("cp932"))
    assert xml.findtext("music/difficulty/exhaust/difnum") == "100"
    report = cast(dict[str, object], json.loads((output / "ksm2sdvx-report.json").read_text()))
    assert "music/3000_synthetic/3000_synthetic_3e.vox" in cast(list[str], report["files"])


def test_package_rejects_missing_inputs_for_supplied_jackets(tmp_path: Path) -> None:
    manifest = _inputs(tmp_path)
    (manifest.parent / "jacket.png").unlink()
    output = tmp_path / "mod"
    with pytest.raises(PackageError, match="Missing asset: jacket.png"):
        build_package(
            load_package_config(manifest),
            destination=output,
            options=ConversionOptions(),
            profile=DEFAULT_PROFILE,
        )
    assert not output.exists()


def test_package_uses_tempo_range_without_display_bpm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _inputs(tmp_path)
    path = manifest.parent / "chart.kson"
    data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    cast(dict[str, object], data["meta"]).pop("disp_bpm")
    data["beat"] = {"bpm": [[0, 135], [960, 172.5]]}
    path.write_text(json.dumps(data), encoding="utf-8")
    _stub_package_media(monkeypatch)
    output = tmp_path / "mod"
    build_package(
        load_package_config(manifest),
        destination=output,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
        renderer=_PackageRenderer(),
    )
    xml = ET.fromstring((output / "others/music_db.merged.xml").read_bytes().decode("cp932"))
    assert xml.findtext("music/info/bpm_min") == "13500"
    assert xml.findtext("music/info/bpm_max") == "17250"
    assert not list(output.rglob("general_sampler_*.s3p"))


@pytest.mark.parametrize("fail_after", [None, 1])
@pytest.mark.parametrize("with_keysounds", [False, True])
def test_package_renders_each_difficulty_and_publishes_only_complete_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after: int | None,
    with_keysounds: bool,
) -> None:
    manifest = _inputs(tmp_path)
    source = manifest.parent
    if with_keysounds:
        chart = source / "chart.kson"
        data = cast(dict[str, object], json.loads(chart.read_text(encoding="utf-8")))
        data["note"] = {"fx": [[0], []]}
        cast(dict[str, object], data["audio"])["key_sound"] = {
            "fx": {"chip_event": {"sample.wav": [[0], []]}}
        }
        chart.write_text(json.dumps(data), encoding="utf-8")
        (source / "sample.wav").write_bytes(b"sample")
    (source / "advanced.kson").write_bytes((source / "chart.kson").read_bytes())
    manifest.write_text(
        MANIFEST.replace(
            "[jacket]", '[[charts]]\npath = "advanced.kson"\nslot = "advanced"\n\n[jacket]'
        ),
        encoding="utf-8",
    )
    config = load_package_config(manifest)
    music = _stub_package_media(monkeypatch)
    renderer = _PackageRenderer(fail_after=fail_after)
    output = tmp_path / "mod"
    if fail_after is not None:
        with pytest.raises(MusicError, match="Renderer failed"):
            build_package(
                config,
                destination=output,
                options=ConversionOptions(strict=True),
                profile=DEFAULT_PROFILE,
                renderer=renderer,
            )
        assert len(renderer.requests) == 2 and not output.exists()
        return
    build_package(
        config,
        destination=output,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
        renderer=renderer,
    )
    assert len(renderer.requests) == len(music.full) == 2
    assert all(request.settings.offset_ms == 0 for request in music.full)
    assert all(request.settings.source_volume == 1 for request in music.full)
    assert len(music.previews) == 1
    assert music.previews[0].source.resolved_path == source / "music.wav"
    assert music.previews[0].settings.offset_ms == 0
    folder = output / "music/3000_synthetic"
    assert (folder / "3000_synthetic_3e.s3v").read_bytes() == b"chart audio 1"
    assert (folder / "3000_synthetic_2a.s3v").read_bytes() == b"chart audio 2"
    assert (folder / "3000_synthetic_pre.s3v").read_bytes() == b"original preview"
    if with_keysounds:
        assert (folder / "general_sampler_3e.s3p").read_bytes() == (
            folder / "general_sampler_2a.s3p"
        ).read_bytes()
        assert isinstance(music.encoder, SilentS3vEncoder) and music.encoder.calls == 0
    else:
        assert not list(folder.glob("general_sampler_*.s3p"))
    report = cast(dict[str, object], json.loads((output / "ksm2sdvx-report.json").read_text()))
    audio = cast(dict[str, object], report["music"])
    rendered_charts = cast(list[dict[str, object]], audio["charts"])
    assert [item["gain_db"] for item in rendered_charts] == [1, 2]


@pytest.mark.parametrize("fail_bank", [False, True])
def test_package_strict_consumes_file_keysounds_only_after_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_bank: bool
) -> None:
    manifest = _inputs(tmp_path)
    chart = manifest.parent / "chart.kson"
    chart.write_text(
        document(
            note={"fx": [[0, [240, 240]], []]},
            audio={
                "bgm": {"filename": "music.wav", "preview": {"offset": 250, "duration": 1500}},
                "audio_effect": {"fx": {"long_event": {"gate": [[240], []]}}},
                "key_sound": {"fx": {"chip_event": {"sample.wav": [[0], []]}}},
            },
        ),
        encoding="utf-8",
    )
    (manifest.parent / "sample.wav").write_bytes(b"sample")
    _stub_package_media(monkeypatch)
    if fail_bank:

        def missing_assets(anchor: str) -> Path:
            return tmp_path / "missing"

        monkeypatch.setattr("ksm2sdvx.music.sampler.files", missing_assets)
    renderer = _PackageRenderer()
    output = tmp_path / "mod"
    if fail_bank:
        with pytest.raises(MusicError, match="Cannot copy bundled silent keysound bank"):
            build_package(
                load_package_config(manifest),
                destination=output,
                options=ConversionOptions(strict=True),
                profile=DEFAULT_PROFILE,
                renderer=renderer,
            )
        assert not output.exists()
        return
    build_package(
        load_package_config(manifest),
        destination=output,
        options=ConversionOptions(strict=True),
        profile=DEFAULT_PROFILE,
        renderer=renderer,
    )
    assert [sample.id for sample in renderer.requests[0].samples] == ["sample.wav"]
    vox = (output / "music/3000_synthetic/3000_synthetic_3e.vox").read_text(encoding="utf-8")
    assert "001,01,00\t0\t2" in vox
    bank_name = "music/3000_synthetic/general_sampler_3e.s3p"
    assert (output / bank_name).read_bytes().startswith(b"S3P0")
    report = cast(dict[str, object], json.loads((output / "ksm2sdvx-report.json").read_text()))
    assert bank_name in cast(list[str], report["files"])
    audio = cast(dict[str, object], report["music"])
    rendered_charts = cast(list[dict[str, object]], audio["charts"])
    assert rendered_charts[0]["native_keysounds"] == {
        "sample": 2,
        "bank": "general_sampler_3e.s3p",
        "silent": True,
    }


def test_package_rendering_does_not_bypass_unrelated_strict_omissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _inputs(tmp_path)
    chart = manifest.parent / "chart.kson"
    chart.write_text(
        document(
            camera={"cam": {"body": {"zoom_side": [[0, 1]]}}},
            audio={"bgm": {"filename": "music.wav", "preview": {"offset": 0, "duration": 1000}}},
        ),
        encoding="utf-8",
    )
    _stub_package_media(monkeypatch)
    renderer = _PackageRenderer()
    output = tmp_path / "mod"
    with pytest.raises(UnsupportedFeaturesError, match="Strict conversion"):
        build_package(
            load_package_config(manifest),
            destination=output,
            options=ConversionOptions(strict=True),
            profile=DEFAULT_PROFILE,
            renderer=renderer,
        )
    assert len(renderer.requests) == 1 and not output.exists()
