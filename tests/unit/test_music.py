"""Audio gain calculation and validation without external processing."""

import math
import sys
from pathlib import Path
from typing import cast

import pytest

from ksm2sdvx.music import (
    FfmpegMusicProcessor,
    LoudnessMeasurement,
    MusicError,
    MusicRequest,
    S3vMusicSettings,
    WindowsWmaProEncoder,
    normalization_gain,
)
from ksm2sdvx.resources.models import ResourceRecord


def test_gain_depends_on_loudness_not_true_peak() -> None:
    settings = S3vMusicSettings()
    assert normalization_gain(LoudnessMeasurement(-20, -12), settings) == pytest.approx(10)
    assert normalization_gain(LoudnessMeasurement(-20, -2), settings) == pytest.approx(10)
    assert normalization_gain(LoudnessMeasurement(-8, 3), settings) == pytest.approx(-2)
    quiet = S3vMusicSettings(source_volume=0.5)
    assert normalization_gain(LoudnessMeasurement(-20, -12), quiet) == pytest.approx(
        10 + 20 * math.log10(0.5)
    )


@pytest.mark.parametrize(
    "settings",
    [
        S3vMusicSettings(target_lufs=float("nan")),
        S3vMusicSettings(source_volume=0),
        S3vMusicSettings(preview_start_ms=0),
        S3vMusicSettings(preview_start_ms=0, preview_duration_ms=0),
        S3vMusicSettings(gain_db=float("inf")),
        S3vMusicSettings(offset_ms=True),
        S3vMusicSettings(offset_ms=10**400),
        S3vMusicSettings(preview_start_ms=0, preview_duration_ms=10**400),
        S3vMusicSettings(source_volume=10**400),
        S3vMusicSettings(target_lufs=cast(float, cast(object, "-11"))),
    ],
)
def test_invalid_settings_fail_before_tools(settings: S3vMusicSettings) -> None:
    with pytest.raises(MusicError):
        normalization_gain(LoudnessMeasurement(-20, -12), settings)


@pytest.mark.parametrize("field", ["true", '"invalid"', "9" * 400, "null", '"-inf"'])
def test_malformed_tool_measurements_are_expected_errors(tmp_path: Path, field: str) -> None:
    class InvalidMeasurementProcessor(FfmpegMusicProcessor):
        def _run(self, arguments: list[str]) -> str:
            return '{"input_i":' + field + ',"input_tp":"-2"}'

    with pytest.raises(MusicError):
        InvalidMeasurementProcessor().analyze(tmp_path / "source.wav")


def test_song_rejects_mismatched_normalization_before_writing(tmp_path: Path) -> None:
    source = ResourceRecord("source.wav", tmp_path / "source.wav", False, True, ())
    with pytest.raises(MusicError, match="same normalization settings"):
        FfmpegMusicProcessor().process_song(
            MusicRequest(source, tmp_path / "full.s3v", S3vMusicSettings()),
            MusicRequest(
                source,
                tmp_path / "preview.s3v",
                S3vMusicSettings(
                    target_lufs=-15,
                    preview_start_ms=0,
                    preview_duration_ms=500,
                ),
            ),
        )
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize(
    "settings",
    [
        S3vMusicSettings(),
        S3vMusicSettings(preview_start_ms=0, preview_duration_ms=500, offset_ms=100),
        S3vMusicSettings(preview_start_ms=0, preview_duration_ms=500, gain_db=0),
    ],
)
def test_preview_reference_rejects_conflicting_timing_or_gain(
    tmp_path: Path, settings: S3vMusicSettings
) -> None:
    source = ResourceRecord("source.wav", tmp_path / "source.wav", False, True, ())
    with pytest.raises(MusicError):
        FfmpegMusicProcessor().process_preview(
            MusicRequest(source, tmp_path / "preview.s3v", settings)
        )
    assert not tuple(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows encoder failure")
def test_native_encoder_rejects_unsupported_platform(tmp_path: Path) -> None:
    with pytest.raises(MusicError, match="requires the Windows"):
        WindowsWmaProEncoder().encode(tmp_path / "input.wav", tmp_path / "output.s3v")
