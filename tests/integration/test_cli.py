import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from tests.conftest import document

from ksm2sdvx.chart.application import write_chart_files
from ksm2sdvx.cli import main
from ksm2sdvx.common.errors import OutputError


def run_cli(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ksm2sdvx", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


def test_chart_command_and_report(tmp_path: Path) -> None:
    source = tmp_path / "chart.kson"
    source.write_text("\ufeff" + document(), encoding="utf-8")
    result = run_cli(tmp_path, "chart", str(source))
    assert result.returncode == 0, result.stderr
    output = tmp_path / "output/chart.vox"
    assert output.exists() and b"\r" not in output.read_bytes()
    report = cast(dict[str, object], json.loads(output.with_suffix(".report.json").read_text()))
    assert report["schema_version"] == 1 and "features" in report
    assert "UTF8_BOM" in result.stderr


def test_inspect_command_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "chart.kson"
    source.write_text(document(audio={"bgm": {"filename": "missing.ogg"}}), encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    result = run_cli(tmp_path, "inspect", str(source), "--root", str(tmp_path))
    assert result.returncode == 1 and not result.stderr
    inspection = cast(dict[str, object], json.loads(result.stdout))
    assert inspection["valid"] is False and inspection["schema_version"] == 2
    assert set(tmp_path.rglob("*")) == before


def test_cli_failure_codes_and_strict_no_output(tmp_path: Path) -> None:
    source = tmp_path / "chart.kson"
    source.write_text(document(beat={"bpm": [[0, 120]], "stop": [[240, 240]]}), encoding="utf-8")
    result = run_cli(tmp_path, "chart", str(source), "--strict")
    assert result.returncode == 1 and "Strict conversion" in result.stderr
    assert not (tmp_path / "output").exists()
    assert run_cli(tmp_path, "chart").returncode == 2
    assert run_cli(tmp_path, "chart", str(source), "--curve-step", "7").returncode == 1
    assert run_cli(tmp_path, "chart", str(source), "-o", str(source)).returncode == 1
    assert run_cli(tmp_path, "inspect").returncode == 2
    assert (
        run_cli(tmp_path, "inspect", str(source), "--root", str(tmp_path), "--strict").returncode
        == 1
    )


def test_inspect_success_options(tmp_path: Path) -> None:
    source = tmp_path / "chart.kson"
    source.write_text(document(), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run_cli(
        tmp_path,
        "inspect",
        str(source),
        "--root",
        str(tmp_path),
        "--strict",
        "--curve-step",
        "20",
    )
    assert result.returncode == 0, result.stderr
    inspection = cast(dict[str, object], json.loads(result.stdout))
    assert inspection["valid"] is True
    assert '"curve_step": 20' in result.stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_chart_application_is_independent_of_cli(tmp_path: Path) -> None:
    from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions
    from ksm2sdvx.chart.application import convert_chart_file

    source = tmp_path / "source.kson"
    source.write_text(document(), encoding="utf-8")
    result = convert_chart_file(
        source,
        output=tmp_path / "custom.vox",
        options=ConversionOptions(),
        profile=DEFAULT_PROFILE,
    )
    assert result.destination.is_file() and result.report_path.is_file()
    assert result.report.schema_version == 1


def test_unexpected_programming_errors_are_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: Path) -> None:
        raise IndexError("programming failure")

    monkeypatch.setattr("ksm2sdvx.chart.application.load_kson", broken)
    with pytest.raises(IndexError):
        main(["chart", "example.kson"])


def test_writer_stages_both_before_replacing(tmp_path: Path) -> None:
    output = tmp_path / "chart.vox"
    output.write_text("original", encoding="utf-8")
    output.with_suffix(".report.json").mkdir()
    with pytest.raises(OutputError):
        write_chart_files(output, "replacement", "report")
    assert output.read_text() == "original"
    assert not list(tmp_path.glob(".ksm2sdvx-*"))


def _media_input(directory: Path, *, audio: bool) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or shutil.which("ffprobe") is None:
        pytest.skip("Media commands require FFmpeg and FFprobe")
    source = directory / ("source.wav" if audio else "source.png")
    arguments = (
        ["-i", "sine=frequency=440:duration=3", "-ac", "2"]
        if audio
        else ["-i", "color=c=red:s=100x50", "-frames:v", "1"]
    )
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", *arguments, str(source)],
        capture_output=True,
        check=True,
    )
    return source


def test_jacket_command_defaults_and_options(tmp_path: Path) -> None:
    source = _media_input(tmp_path, audio=False)
    before = source.read_bytes()
    result = run_cli(tmp_path, "jacket", str(source))
    assert result.returncode == 0, result.stderr
    output = tmp_path / "output/source_300.png"
    assert struct.unpack_from(">II", output.read_bytes(), 16) == (300, 300)
    assert output.read_bytes()[24:26] == bytes((8, 2))
    custom = tmp_path / "selector.png"
    result = run_cli(
        tmp_path,
        "jacket",
        str(source),
        "-o",
        str(custom),
        "--size",
        "128",
        "--ffmpeg",
        "ffmpeg",
        "--ffprobe",
        "ffprobe",
    )
    assert result.returncode == 0, result.stderr
    assert struct.unpack_from(">II", custom.read_bytes(), 16) == (128, 128)
    assert source.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Audio encoding requires Windows Media Format")
def test_audio_command_defaults_and_preview(tmp_path: Path) -> None:
    source = _media_input(tmp_path, audio=True)
    before = source.read_bytes()
    result = run_cli(tmp_path, "audio", str(source))
    assert result.returncode == 0, result.stderr
    output = tmp_path / "output/source.s3v"
    assert output.read_bytes().startswith(bytes.fromhex("3026b275"))
    loudness = float(result.stdout.split("Output loudness: ")[1].split()[0])
    assert loudness == pytest.approx(-11, abs=0.2)
    custom = tmp_path / "preview.s3v"
    result = run_cli(
        tmp_path,
        "audio",
        str(source),
        "-o",
        str(custom),
        "--target-lufs",
        "-14",
        "--true-peak-dbtp",
        "-2",
        "--preview-start-ms",
        "500",
        "--preview-duration-ms",
        "1500",
    )
    assert result.returncode == 0, result.stderr
    assert custom.read_bytes().startswith(bytes.fromhex("3026b275"))
    for path in (output, custom):
        data = path.read_bytes()
        assert struct.unpack("<4sII", data[-32:-20]) == (b"S3V0", 32, len(data) - 32)
    assert source.read_bytes() == before


def test_media_command_failures(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "audio").returncode == 2
    assert run_cli(tmp_path, "jacket", "missing.png", "--size", "200").returncode == 2
    assert run_cli(tmp_path, "jacket", "missing.png").returncode == 1
    assert run_cli(tmp_path, "audio", "missing.wav").returncode == 1
    assert run_cli(tmp_path, "audio", "missing.wav", "--target-lufs", "nan").returncode == 1
    assert run_cli(tmp_path, "audio", "missing.wav", "--preview-start-ms", "0").returncode == 1
    assert not (tmp_path / "output").exists()
