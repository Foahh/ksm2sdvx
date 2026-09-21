"""Loudness measurement, constant-gain normalization, and S3V audio output."""

import json
import math
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import cast

from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.music._windows import WindowsWmaProEncoder
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.interfaces import S3vEncoder
from ksm2sdvx.music.models import (
    LoudnessMeasurement,
    MusicRequest,
    MusicResult,
    S3vMusicSettings,
)
from ksm2sdvx.resources.models import ProcessedResource


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MusicError(f"The {name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise MusicError(f"The {name} must be a finite number") from exc
    if not math.isfinite(number):
        raise MusicError(f"The {name} must be a finite number")
    return number


def normalization_gain(measurement: LoudnessMeasurement, settings: S3vMusicSettings) -> float:
    """Use a single gain, retaining dynamics and respecting the measured peak."""
    _validate_settings(settings)
    loudness = _finite_number(measurement.integrated_lufs, "integrated loudness")
    peak = _finite_number(measurement.true_peak_dbtp, "true peak")
    target = settings.target_lufs + 20 * math.log10(settings.source_volume)
    return _finite_number(min(target - loudness, settings.true_peak_dbtp - peak), "audio gain")


def _validate_settings(settings: S3vMusicSettings) -> None:
    for name, value in (
        ("target loudness", settings.target_lufs),
        ("true peak ceiling", settings.true_peak_dbtp),
        ("source volume", settings.source_volume),
    ):
        _finite_number(value, name)
    if not -70 <= settings.target_lufs <= 0:
        raise MusicError("Target loudness must be between -70 and 0 LUFS")
    if not -20 <= settings.true_peak_dbtp <= 0:
        raise MusicError("True peak ceiling must be between -20 and 0 dBTP")
    if settings.source_volume <= 0:
        raise MusicError("Audio volume must be positive for loudness normalization")
    if type(settings.offset_ms) is not int:
        raise MusicError("Audio offset must be an integer number of milliseconds")
    if not -(2**31) <= settings.offset_ms <= 2**31 - 1:
        raise MusicError("Audio offset exceeds the signed 32-bit millisecond range")
    if (settings.preview_start_ms is None) != (settings.preview_duration_ms is None):
        raise MusicError("Preview start and duration must be supplied together")
    if settings.preview_start_ms is not None:
        if type(settings.preview_start_ms) is not int or settings.preview_start_ms < 0:
            raise MusicError("Preview start must be a nonnegative integer number of milliseconds")
        duration = settings.preview_duration_ms
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise MusicError("Preview duration must be a positive integer number of milliseconds")
        if settings.preview_start_ms > 2**31 - 1 or duration > 2**31 - 1:
            raise MusicError("Preview timing exceeds the signed 32-bit millisecond range")
    if settings.gain_db is not None:
        _finite_number(settings.gain_db, "audio gain")


def _timing_filters(settings: S3vMusicSettings) -> list[str]:
    if settings.preview_start_ms is not None and settings.preview_duration_ms is not None:
        return [
            f"atrim=start={settings.preview_start_ms / 1000:.3f}:duration={settings.preview_duration_ms / 1000:.3f}",
            "asetpts=PTS-STARTPTS",
        ]
    if settings.offset_ms > 0:
        return [f"atrim=start={settings.offset_ms / 1000:.3f}", "asetpts=PTS-STARTPTS"]
    if settings.offset_ms < 0:
        return [f"adelay={-settings.offset_ms}:all=1"]
    return []


def _read_fields(stderr: str) -> dict[str, object]:
    start = stderr.rfind("{")
    stop = stderr.rfind("}")
    if start < 0 or stop < start:
        raise MusicError("FFmpeg returned no loudness measurement")
    try:
        data = cast(object, json.loads(stderr[start : stop + 1]))
    except ValueError as exc:
        raise MusicError("FFmpeg returned malformed loudness measurements") from exc
    if not isinstance(data, dict):
        raise MusicError("FFmpeg returned an invalid loudness measurement")
    return cast(dict[str, object], data)


def _measurement_number(fields: dict[str, object], key: str) -> float:
    value = fields.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        raise MusicError(f"FFmpeg loudness field {key} is missing or nonnumeric")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise MusicError(f"FFmpeg loudness field {key} is nonnumeric") from exc
    if not math.isfinite(number):
        raise MusicError("Audio is silent or too short to measure finite loudness or peak")
    return number


def _read_measurement(stderr: str) -> LoudnessMeasurement:
    fields = _read_fields(stderr)
    return LoudnessMeasurement(
        _measurement_number(fields, "input_i"), _measurement_number(fields, "input_tp")
    )


def _request_paths(request: MusicRequest[S3vMusicSettings]) -> tuple[Path, Path]:
    source = request.source.resolved_path
    if source is None or request.source.preset:
        raise MusicError("Music processing requires a file resource")
    destination = request.destination
    if destination.suffix.lower() != ".s3v":
        raise MusicError("Music destination must have the .s3v extension")
    try:
        if not source.is_file():
            raise MusicError(f"Audio source does not exist: {source}")
        if source.resolve() == destination.resolve():
            raise MusicError("Audio destination must not overwrite its source")
    except OSError as exc:
        raise MusicError(f"Unable to resolve audio paths: {exc}") from exc
    return source, destination


class FfmpegMusicProcessor:
    """Measure with FFmpeg, apply a volume filter, then encode WMA Professional.

    The loudnorm filter is used for measurement only. Conversion uses a constant
    volume filter, so no compression or time-varying normalization is introduced.
    """

    def __init__(self, ffmpeg: str = "ffmpeg", *, encoder: S3vEncoder | None = None) -> None:
        if type(ffmpeg) is not str or not ffmpeg.strip() or "\0" in ffmpeg:
            raise MusicError("An FFmpeg executable must be specified")
        self.ffmpeg = ffmpeg
        self.encoder = encoder if encoder is not None else WindowsWmaProEncoder()

    def _run(self, arguments: list[str]) -> str:
        try:
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-xerror", *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, ValueError) as exc:
            raise MusicError(f"Unable to run FFmpeg: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip()[-2000:]
            raise MusicError(f"FFmpeg audio processing failed: {detail}")
        return result.stderr

    def analyze(self, source: Path, *, offset_ms: int = 0) -> LoudnessMeasurement:
        return self._analyze(source, S3vMusicSettings(offset_ms=offset_ms))

    def _analyze(self, source: Path, settings: S3vMusicSettings) -> LoudnessMeasurement:
        return _read_measurement(self._analysis_output(source, settings))

    def _analysis_output(self, source: Path, settings: S3vMusicSettings) -> str:
        _validate_settings(settings)
        filters = [
            "aresample=44100",
            "aformat=sample_fmts=dbl:channel_layouts=stereo",
            *_timing_filters(settings),
            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        ]
        return self._run(
            [
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-af",
                ",".join(filters),
                "-f",
                "null",
                "-",
            ]
        )

    def process_song(
        self,
        full: MusicRequest[S3vMusicSettings],
        preview: MusicRequest[S3vMusicSettings],
    ) -> tuple[MusicResult, MusicResult]:
        """Choose one gain against the full track loudness and both segment peaks.

        Requests must share a source and normalization settings. Each destination
        is staged independently; the package application stages the complete pair.
        """
        _validate_settings(full.settings)
        _validate_settings(preview.settings)
        source = full.source.resolved_path
        preview_source = preview.source.resolved_path
        if (
            source is None
            or preview_source is None
            or full.source.preset
            or preview.source.preset
            or source.resolve() != preview_source.resolve()
        ):
            raise MusicError("A full track and preview must reference the same audio file")
        if full.destination.resolve() == preview.destination.resolve():
            raise MusicError("A full track and preview must have distinct output destinations")
        if full.settings.preview_start_ms is not None or preview.settings.preview_start_ms is None:
            raise MusicError(
                "Song processing requires a full track and an explicit preview interval"
            )
        full_normalization = (
            full.settings.target_lufs,
            full.settings.true_peak_dbtp,
            full.settings.source_volume,
        )
        preview_normalization = (
            preview.settings.target_lufs,
            preview.settings.true_peak_dbtp,
            preview.settings.source_volume,
        )
        if full_normalization != preview_normalization:
            raise MusicError("A full track and preview must use the same normalization settings")
        if full.settings.gain_db is not None or preview.settings.gain_db is not None:
            raise MusicError(
                "Song processing selects its shared gain; omit individual gain overrides"
            )
        _request_paths(full)
        _request_paths(preview)
        measurement = self._analyze(source, full.settings)
        preview_peak = _measurement_number(
            _read_fields(self._analysis_output(source, preview.settings)), "input_tp"
        )
        gain = min(
            normalization_gain(measurement, full.settings),
            full.settings.true_peak_dbtp - preview_peak,
        )
        full_result = self._process(
            replace(full, settings=replace(full.settings, gain_db=gain)),
            measurement=measurement,
            peak=measurement.true_peak_dbtp,
        )
        preview_result = self._process(
            replace(preview, settings=replace(preview.settings, gain_db=gain)), peak=preview_peak
        )
        return full_result, preview_result

    def process(self, request: MusicRequest[S3vMusicSettings]) -> MusicResult:
        return self._process(request)

    def process_preview(self, request: MusicRequest[S3vMusicSettings]) -> MusicResult:
        """Normalize a dry preview against its original full-track loudness.

        The preview peak may reduce the gain. Chart offsets and rendered
        difficulty measurements never influence this operation.
        """
        settings = request.settings
        _validate_settings(settings)
        if settings.preview_start_ms is None:
            raise MusicError("Preview processing requires an explicit preview interval")
        if settings.offset_ms != 0 or settings.gain_db is not None:
            raise MusicError("Preview processing selects its gain and uses original audio timing")
        source, _ = _request_paths(request)
        reference = self._analyze(
            source,
            replace(settings, preview_start_ms=None, preview_duration_ms=None),
        )
        preview_peak = _measurement_number(
            _read_fields(self._analysis_output(source, settings)), "input_tp"
        )
        target = settings.target_lufs + 20 * math.log10(settings.source_volume)
        gain = min(target - reference.integrated_lufs, settings.true_peak_dbtp - preview_peak)
        result = self._process(
            replace(request, settings=replace(settings, gain_db=gain)), peak=preview_peak
        )
        return replace(result, measurement=reference)

    def _process(
        self,
        request: MusicRequest[S3vMusicSettings],
        *,
        measurement: LoudnessMeasurement | None = None,
        peak: float | None = None,
    ) -> MusicResult:
        settings = request.settings
        _validate_settings(settings)
        source, destination = _request_paths(request)
        if settings.gain_db is None or settings.preview_start_ms is None:
            if measurement is None:
                measurement = self._analyze(source, settings)
            peak = measurement.true_peak_dbtp
            gain = (
                normalization_gain(measurement, settings)
                if settings.gain_db is None
                else settings.gain_db
            )
            description = f"Measured {measurement.integrated_lufs:.2f} LUFS and {peak:.2f} dBTP"
        else:
            if peak is None:
                peak = _measurement_number(
                    _read_fields(self._analysis_output(source, settings)), "input_tp"
                )
            gain = settings.gain_db
            description = f"Measured preview peak {peak:.2f} dBTP"
        if peak + gain > settings.true_peak_dbtp + 0.05:
            raise MusicError("The supplied shared audio gain exceeds the preview true-peak ceiling")
        target = settings.target_lufs + 20 * math.log10(settings.source_volume)
        diagnostics = [
            Diagnostic(
                code="AUDIO_NORMALIZED",
                severity=Severity.INFO,
                stage=Stage.MUSIC,
                message=f"{description}; applied {gain:.3f} dB constant gain.",
                feature="audio.normalization",
                source_path=str(source),
            )
        ]
        if measurement is not None and measurement.integrated_lufs + gain < target - 0.05:
            diagnostics.append(
                Diagnostic(
                    code="AUDIO_PEAK_LIMITED",
                    severity=Severity.WARNING,
                    stage=Stage.MUSIC,
                    message=f"True-peak headroom limits output to approximately {measurement.integrated_lufs + gain:.2f} LUFS; requested {target:.2f} LUFS.",
                    feature="audio.normalization",
                    source_path=str(source),
                )
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".ksm2sdvx-audio-", dir=destination.parent
            ) as work:
                pcm = Path(work) / "normalized.wav"
                encoded = Path(work) / "encoded.s3v"
                filters = [
                    "aresample=44100",
                    "aformat=sample_fmts=dbl:channel_layouts=stereo",
                    *_timing_filters(settings),
                    f"volume={gain:.9f}dB:precision=double",
                ]
                self._run(
                    [
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(source),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-sn",
                        "-dn",
                        "-af",
                        ",".join(filters),
                        "-c:a",
                        "pcm_s16le",
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        "-f",
                        "wav",
                        str(pcm),
                    ]
                )
                self.encoder.encode(pcm, encoded)
                if not encoded.is_file() or encoded.stat().st_size == 0:
                    raise MusicError("Audio encoder did not produce its output file")
                encoded_analysis = self._analysis_output(encoded, S3vMusicSettings())
                encoded_fields = _read_fields(encoded_analysis)
                encoded_peak = _measurement_number(encoded_fields, "input_tp")
                output_measurement = (
                    _read_measurement(encoded_analysis)
                    if measurement is not None or encoded_fields.get("input_i") != "-inf"
                    else None
                )
                encoded_level = (
                    f"{output_measurement.integrated_lufs:.2f} LUFS and "
                    if output_measurement is not None
                    else ""
                )
                diagnostics.append(
                    Diagnostic(
                        code="AUDIO_ENCODED",
                        severity=Severity.INFO,
                        stage=Stage.MUSIC,
                        message=f"Decoded output measures {encoded_level}{encoded_peak:.2f} dBTP.",
                        feature="audio.normalization",
                        source_path=str(source),
                    )
                )
                if encoded_peak > settings.true_peak_dbtp + 0.05:
                    diagnostics.append(
                        Diagnostic(
                            code="AUDIO_CODEC_PEAK",
                            severity=Severity.WARNING,
                            stage=Stage.MUSIC,
                            message=f"Lossy encoding raised true peak to {encoded_peak:.2f} dBTP; the {settings.true_peak_dbtp:.2f} dBTP ceiling bounds the signal before encoding.",
                            feature="audio.normalization",
                            source_path=str(source),
                        )
                    )
                os.replace(encoded, destination)
        except OSError as exc:
            raise MusicError(f"Unable to write audio output: {exc}") from exc
        return MusicResult(
            ProcessedResource(destination, request.source.uses),
            tuple(diagnostics),
            measurement,
            gain,
            output_measurement,
        )
