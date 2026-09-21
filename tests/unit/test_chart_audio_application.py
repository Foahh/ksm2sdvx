"""Rendering/encoding composition and safe publication of chart audio."""

import json
from pathlib import Path
from typing import cast

import pytest
from tests.conftest import document

from ksm2sdvx.cli import main
from ksm2sdvx.music import (
    FfmpegMusicProcessor,
    MusicError,
    MusicRequest,
    MusicResult,
    S3vMusicSettings,
)
from ksm2sdvx.music.render_models import AudioRenderRequest, AudioRenderResult
from ksm2sdvx.pipeline.audio import convert_chart_audio_file
from ksm2sdvx.resources.models import ProcessedResource


class RecordingRenderer:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[AudioRenderRequest] = []
        self.fail = fail

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        self.requests.append(request)
        request.destination.write_bytes(b"rendered audio")
        if self.fail:
            raise MusicError("Rendering failed")
        return AudioRenderResult(ProcessedResource(request.destination, ()), frames=44100)


class RecordingProcessor(FfmpegMusicProcessor):
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[MusicRequest[S3vMusicSettings]] = []
        self.fail = fail

    def process(self, request: MusicRequest[S3vMusicSettings]) -> MusicResult:
        self.requests.append(request)
        source = request.source.resolved_path
        assert source is not None
        assert source.read_bytes() == b"rendered audio"
        request.destination.write_bytes(b"encoded audio")
        if self.fail:
            raise MusicError("Encoding failed")
        return MusicResult(ProcessedResource(request.destination, ()), gain_db=2.5)


def _chart(directory: Path) -> Path:
    chart = directory / "chart.kson"
    chart.write_text(
        document(audio={"bgm": {"filename": "music.wav", "offset": 250, "vol": 0.5}}),
        encoding="utf-8",
    )
    (directory / "music.wav").write_bytes(b"original audio")
    return chart


def test_chart_audio_uses_authored_timing_once_and_publishes_report(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    renderer = RecordingRenderer()
    processor = RecordingProcessor()
    output = tmp_path / "converted.s3v"
    result = convert_chart_audio_file(chart, output=output, renderer=renderer, processor=processor)
    assert output.read_bytes() == b"encoded audio"
    assert renderer.requests[0].program.offset_frames == 11025
    assert renderer.requests[0].program.bgm_volume == 0.5
    settings = processor.requests[0].settings
    assert settings.offset_ms == 0 and settings.source_volume == 1
    assert settings.target_lufs == -11 and settings.true_peak_dbtp == -1
    report = cast(dict[str, object], json.loads(result.report_path.read_text(encoding="utf-8")))
    assert report["source"] == chart.name
    assert str(tmp_path) not in result.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("render_failure", [True, False])
def test_chart_audio_failure_preserves_existing_outputs(
    tmp_path: Path, render_failure: bool
) -> None:
    chart = _chart(tmp_path)
    output = tmp_path / "converted.s3v"
    report = output.with_suffix(".report.json")
    output.write_bytes(b"old audio")
    report.write_bytes(b"old report")
    with pytest.raises(MusicError, match="failed"):
        convert_chart_audio_file(
            chart,
            output=output,
            renderer=RecordingRenderer(fail=render_failure),
            processor=RecordingProcessor(fail=not render_failure),
        )
    assert output.read_bytes() == b"old audio" and report.read_bytes() == b"old report"
    assert not tuple(tmp_path.glob(".ksm2sdvx-chart-audio-*"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["--offset-ms", "0"],
        ["--source-volume", "1"],
        ["--preview-start-ms", "0"],
        ["--preview-duration-ms", "1000"],
        ["raw.wav"],
    ],
)
def test_chart_audio_rejects_raw_input_overrides(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["audio", "--chart", "chart.kson", *arguments])
    assert error.value.code == 2


def test_audio_strict_rejects_custom_slam_before_rendering(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    chart.write_text(
        document(
            audio={
                "bgm": {"filename": "music.wav"},
                "key_sound": {"laser": {"vol": [[0, 0.5]]}},
            }
        ),
        encoding="utf-8",
    )
    renderer = RecordingRenderer()
    with pytest.raises(MusicError, match="Strict audio"):
        convert_chart_audio_file(
            chart, output=tmp_path / "converted.s3v", strict=True, renderer=renderer
        )
    assert not renderer.requests and not (tmp_path / "converted.s3v").exists()


def test_audio_rendering_does_not_require_vox_tick_alignment(tmp_path: Path) -> None:
    chart = _chart(tmp_path)
    chart.write_text(
        document(note={"fx": [[1], []]}, audio={"bgm": {"filename": "music.wav"}}),
        encoding="utf-8",
    )
    result = convert_chart_audio_file(
        chart,
        output=tmp_path / "audio.s3v",
        strict=True,
        renderer=RecordingRenderer(),
        processor=RecordingProcessor(),
    )
    assert result.destination.is_file()
