"""Audio normalization, timing, failure handling, and native S3V encoding."""

import math
import shutil
import struct
import subprocess
import sys
import wave
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
from ksm2sdvx.resources.models import ResourceRecord, ResourceUse


def _source(path: Path, *, silence: bool = False, loud_intro: bool = False) -> ResourceRecord:
    samples = bytearray()
    for frame in range(44100 * 3):
        amplitude = 0 if silence else round(2000 * math.sin(frame * 2 * math.pi * 440 / 44100))
        if loud_intro and frame < 44100:
            amplitude *= 10
        samples.extend(struct.pack("<hh", amplitude, amplitude))
    with wave.open(str(path), "wb") as audio:
        audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        audio.writeframes(samples)
    return ResourceRecord(path.name, path, False, True, (ResourceUse(path, "music", "/audio/bgm"),))


class _PcmCapture:
    """Capture the signal supplied to the compressed encoder for timing checks."""

    def __init__(self) -> None:
        self.frames = 0
        self.start = b""

    def encode(self, source: Path, destination: Path) -> None:
        with wave.open(str(source), "rb") as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (
                44100,
                2,
                2,
            )
            self.frames = audio.getnframes()
            self.start = audio.readframes(4410)
        shutil.copyfile(source, destination)


@pytest.fixture
def ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is required for audio signal processing tests")
    return executable


def test_gain_preserves_dynamics_and_limits_true_peak() -> None:
    settings = S3vMusicSettings(true_peak_dbtp=-1)
    assert normalization_gain(LoudnessMeasurement(-20, -12), settings) == pytest.approx(9)
    assert normalization_gain(LoudnessMeasurement(-20, -2), settings) == 1
    assert normalization_gain(LoudnessMeasurement(-8, 1), settings) == pytest.approx(-3)
    quiet = S3vMusicSettings(source_volume=0.5)
    assert normalization_gain(LoudnessMeasurement(-20, -12), quiet) == pytest.approx(
        9 + 20 * math.log10(0.5)
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


@pytest.mark.parametrize("offset_ms,expected_frames", [(500, 110250), (-500, 154350)])
def test_kson_offset_trims_positive_and_pads_negative(
    tmp_path: Path, ffmpeg: str, offset_ms: int, expected_frames: int
) -> None:
    source = _source(tmp_path / "source.wav")
    encoder = _PcmCapture()
    result = FfmpegMusicProcessor(ffmpeg, encoder=encoder).process(
        MusicRequest(source, tmp_path / "song.s3v", S3vMusicSettings(offset_ms=offset_ms))
    )
    assert encoder.frames == expected_frames
    assert result.resource.uses == source.uses
    assert result.measurement is not None
    assert result.output_measurement is not None
    assert result.output_measurement.integrated_lufs == pytest.approx(-11, abs=0.1)
    if offset_ms < 0:
        assert encoder.start == bytes(len(encoder.start))
    else:
        assert any(encoder.start)


def test_preview_uses_raw_time_and_shared_gain(tmp_path: Path, ffmpeg: str) -> None:
    source = _source(tmp_path / "source.wav")
    encoder = _PcmCapture()
    processor = FfmpegMusicProcessor(ffmpeg, encoder=encoder)
    full = processor.process(MusicRequest(source, tmp_path / "full.s3v", S3vMusicSettings()))
    preview = processor.process(
        MusicRequest(
            source,
            tmp_path / "preview.s3v",
            S3vMusicSettings(
                offset_ms=-1000,
                preview_start_ms=1000,
                preview_duration_ms=100,
                gain_db=full.gain_db,
            ),
        )
    )
    assert encoder.frames == 4410
    assert preview.gain_db == full.gain_db
    assert preview.measurement is None
    assert any(encoder.start)


def test_song_gain_accounts_for_loud_intro_omitted_by_chart_offset(
    tmp_path: Path, ffmpeg: str
) -> None:
    source = _source(tmp_path / "source.wav", loud_intro=True)
    processor = FfmpegMusicProcessor(ffmpeg, encoder=_PcmCapture())
    full, preview = processor.process_song(
        MusicRequest(source, tmp_path / "full.s3v", S3vMusicSettings(offset_ms=1000)),
        MusicRequest(
            source,
            tmp_path / "preview.s3v",
            S3vMusicSettings(
                preview_start_ms=0,
                preview_duration_ms=500,
            ),
        ),
    )
    assert full.gain_db == preview.gain_db
    assert full.measurement is not None
    assert full.output_measurement is not None
    assert full.gain_db is not None
    assert full.gain_db < normalization_gain(full.measurement, S3vMusicSettings())
    assert full.output_measurement.true_peak_dbtp < -15
    assert any(d.code == "AUDIO_PEAK_LIMITED" for d in full.diagnostics)
    preview_levels = processor.analyze(preview.resource.path)
    assert preview_levels.true_peak_dbtp == pytest.approx(-1, abs=0.05)


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


def test_silence_and_missing_executable_are_expected_errors(tmp_path: Path, ffmpeg: str) -> None:
    source = _source(tmp_path / "silent.wav", silence=True)
    output = tmp_path / "silent.s3v"
    with pytest.raises(MusicError, match="silent"):
        FfmpegMusicProcessor(ffmpeg).process(MusicRequest(source, output, S3vMusicSettings()))
    assert not output.exists()
    with pytest.raises(MusicError, match="Unable to run FFmpeg"):
        FfmpegMusicProcessor(str(tmp_path / "missing-ffmpeg")).analyze(tmp_path / "silent.wav")


def test_encoder_failure_preserves_existing_output(tmp_path: Path, ffmpeg: str) -> None:
    class FailingEncoder:
        def encode(self, source: Path, destination: Path) -> None:
            destination.write_bytes(b"partial")
            raise MusicError("encoder failed")

    source = _source(tmp_path / "source.wav")
    output = tmp_path / "song.s3v"
    output.write_bytes(b"existing")
    with pytest.raises(MusicError, match="encoder failed"):
        FfmpegMusicProcessor(ffmpeg, encoder=FailingEncoder()).process(
            MusicRequest(source, output, S3vMusicSettings())
        )
    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".ksm2sdvx-audio-*"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WMA Professional encoder")
def test_native_s3v_codec_and_loudness(tmp_path: Path, ffmpeg: str) -> None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("FFprobe is required to inspect the encoded stream")
    source = _source(tmp_path / "source.wav")
    output = tmp_path / "song.s3v"
    result = FfmpegMusicProcessor(ffmpeg).process(MusicRequest(source, output, S3vMusicSettings()))
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "compact=p=0",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "codec_name=wmapro" in probe.stdout
    assert "sample_rate=44100" in probe.stdout
    assert "channels=2" in probe.stdout
    assert output.read_bytes()[:16] == bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
    data = output.read_bytes()
    assert struct.unpack("<4sII20s", data[-32:]) == (b"S3V0", 32, len(data) - 32, bytes(20))
    assert result.output_measurement is not None
    assert result.output_measurement.integrated_lufs == pytest.approx(-11, abs=0.2)


@pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows encoder failure")
def test_native_encoder_rejects_unsupported_platform(tmp_path: Path) -> None:
    with pytest.raises(MusicError, match="requires the Windows"):
        WindowsWmaProEncoder().encode(tmp_path / "input.wav", tmp_path / "output.s3v")
