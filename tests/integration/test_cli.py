import json
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
        "--zoom-top-scale",
        "0.1",
        "--zoom-bottom-scale",
        "-0.2",
        "--tilt-scale",
        "0.3",
    )
    assert result.returncode == 0, result.stderr
    inspection = cast(dict[str, object], json.loads(result.stdout))
    assert inspection["valid"] is True
    assert '"curve_step": 20' in result.stdout and '"tilt_scale": 0.3' in result.stdout
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
