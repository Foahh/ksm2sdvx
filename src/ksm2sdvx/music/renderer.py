"""Subprocess boundary for the bundled offline renderer and its audio sources."""

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import cast

from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.common.types import JsonValue, json_ready
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.render_models import AudioRenderRequest, AudioRenderResult, AudioSource
from ksm2sdvx.resources.models import ProcessedResource

_PRESETS = frozenset({"clap", "clap_impact", "clap_punchy", "snare", "snare_lo"})
_UPSTREAM_COMMIT = "41bfdaa7331808aff7239a9ec283cdba01b3b406"
_AUDIO_COMMIT = "c51865f7757f47cffbd530469977aa94332d9826"


def _bundled_file(relative: str) -> Path:
    # Wheels are installed as directories. Resolving resources here keeps imports inert.
    resource = files("ksm2sdvx.music").joinpath("_native", relative)
    if not resource.is_file():
        raise MusicError(
            f"Bundled audio resource is missing: {relative}. Reinstall the Windows x64 package."
        )
    return Path(str(resource))


def bundled_preset(name: str) -> Path:
    if name not in _PRESETS:
        raise MusicError(f"Unknown built-in chip sample: {name}")
    _require_supported_platform()
    return _bundled_file(f"presets/{name}.wav")


def _require_supported_platform() -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise MusicError("Offline chart audio rendering requires Windows x64")


def _renderer_executable() -> Path:
    _require_supported_platform()
    return _bundled_file("ksm2sdvx-render.exe")


def _run(arguments: list[str], *, label: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise MusicError(f"Unable to run {label}: {exc}") from exc


def _receipt(stdout: str) -> dict[str, object]:
    try:
        value = cast(object, json.loads(stdout))
    except ValueError as exc:
        raise MusicError("The audio renderer returned an invalid JSON response") from exc
    if not isinstance(value, dict):
        raise MusicError("The audio renderer response must be an object")
    data = cast(dict[str, object], value)
    if type(data.get("protocol_version")) is not int or data["protocol_version"] != 1:
        raise MusicError("The audio renderer protocol version is unsupported")
    error = data.get("error")
    if isinstance(error, dict):
        fields = cast(dict[str, object], error)
        code, message = fields.get("code"), fields.get("message")
        if isinstance(code, str) and isinstance(message, str):
            raise MusicError(f"Audio rendering failed ({code}): {message}")
        raise MusicError("The audio renderer returned a malformed error")
    return data


def _count(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MusicError(f"The audio renderer returned an invalid {key}")
    return value


def _version(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise MusicError(f"The audio renderer returned an invalid {key}")
    return value


def _validate_pcm(path: Path, frames: int) -> None:
    """Check the produced container against its receipt before replacing output."""
    size = path.stat().st_size
    with path.open("rb") as audio:
        header = audio.read(12)
        if (
            len(header) != 12
            or header[:4] != b"RIFF"
            or header[8:] != b"WAVE"
            or struct.unpack_from("<I", header, 4)[0] + 8 != size
        ):
            raise MusicError("The audio renderer produced an invalid WAV container")
        format_seen = False
        data_seen = False
        while audio.tell() < size:
            chunk = audio.read(8)
            if len(chunk) != 8:
                raise MusicError("The audio renderer produced a truncated WAV chunk")
            length = struct.unpack_from("<I", chunk, 4)[0]
            start = audio.tell()
            if start + length + (length % 2) > size:
                raise MusicError("The audio renderer produced a truncated WAV chunk")
            if chunk[:4] == b"fmt ":
                if length < 16:
                    raise MusicError("The rendered WAV is missing its PCM format")
                fields = struct.unpack("<HHIIHH", audio.read(16))
                if fields != (3, 2, 44100, 352800, 8, 32):
                    raise MusicError("The rendered WAV must be stereo 44100 Hz float32 PCM")
                format_seen = True
            elif chunk[:4] == b"data":
                if data_seen or length != frames * 8:
                    raise MusicError("The rendered WAV frame count differs from its receipt")
                data_seen = True
            audio.seek(start + length + (length % 2))
        if not format_seen or not data_seen:
            raise MusicError("The rendered WAV is missing its format or audio data")


def _validate(request: AudioRenderRequest) -> None:
    program = request.program
    if type(program.sample_rate) is not int or program.sample_rate != 44100:
        raise MusicError("Offline rendering requires a 44100 Hz program")
    if type(program.duration_frames) is not int or program.duration_frames < 0:
        raise MusicError("Render duration must be a nonnegative integer frame count")
    if type(program.offset_frames) is not int:
        raise MusicError("Render offset must be an integer frame count")
    if (
        isinstance(program.bgm_volume, bool)
        or not math.isfinite(program.bgm_volume)
        or program.bgm_volume < 0
    ):
        raise MusicError("Render BGM volume must be finite and nonnegative")
    if request.destination.suffix.lower() != ".wav":
        raise MusicError("The rendered PCM destination must have the .wav extension")
    if request.source.id != "main":
        raise MusicError("The original music resource must have the identifier 'main'")
    for sources in ((request.source, *request.tracks), request.samples):
        ids: set[str] = set()
        for source in sources:
            if not source.id or source.id in ids:
                raise MusicError("Render source identifiers must be nonempty and unique")
            ids.add(source.id)
            if not source.path.is_file():
                raise MusicError(f"Audio source does not exist: {source.path}")
            if source.path.resolve() == request.destination.resolve():
                raise MusicError("Rendered audio must not overwrite an input resource")


class NativeAudioRenderer:
    """Prepare PCM sources and invoke the bundled, isolated DSP executable."""

    def __init__(self, ffmpeg: str = "ffmpeg") -> None:
        if not ffmpeg.strip() or "\0" in ffmpeg:
            raise MusicError("An FFmpeg executable must be specified")
        self.ffmpeg = ffmpeg

    def _decode(self, source: Path, destination: Path) -> None:
        result = _run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-xerror",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-c:a",
                "pcm_f32le",
                "-f",
                "wav",
                str(destination),
            ],
            label="FFmpeg",
        )
        if result.returncode or not destination.is_file():
            raise MusicError(f"Unable to decode audio: {result.stderr.strip()[-2000:]}")

    def render(self, request: AudioRenderRequest) -> AudioRenderResult:
        try:
            return self._render(request)
        except OSError as exc:
            raise MusicError(f"Audio rendering filesystem operation failed: {exc}") from exc

    def _render(self, request: AudioRenderRequest) -> AudioRenderResult:
        _validate(request)
        executable = _renderer_executable()
        request.destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".ksm2sdvx-render-", dir=request.destination.parent
        ) as temporary:
            workspace = Path(temporary)
            decoded: dict[Path, Path] = {}

            def sources(values: tuple[AudioSource, ...]) -> tuple[JsonValue, ...]:
                result: list[JsonValue] = []
                for source in values:
                    original = source.path.resolve()
                    if original not in decoded:
                        path = workspace / f"source-{len(decoded)}.wav"
                        self._decode(original, path)
                        decoded[original] = path
                    result.append({"id": source.id, "path": str(decoded[original])})
                return tuple(result)

            payload: dict[str, JsonValue] = {
                "protocol_version": 1,
                "sample_rate": request.program.sample_rate,
                "duration_frames": request.program.duration_frames,
                "offset_frames": request.program.offset_frames,
                "bgm_volume": request.program.bgm_volume,
                "tracks": sources((request.source, *request.tracks)),
                "samples": sources(request.samples),
                "program": request.program.to_dict(),
            }
            request_path = workspace / "request.json"
            output = workspace / "rendered.wav"
            request_path.write_text(
                json.dumps(json_ready(payload), ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
            process = _run(
                [str(executable), "--request", str(request_path), "--output", str(output)],
                label="the offline audio renderer",
            )
            if process.returncode and not process.stdout.strip():
                raise MusicError(
                    f"The audio renderer exited with code {process.returncode}: "
                    + process.stderr.strip()[-2000:]
                )
            receipt = _receipt(process.stdout)
            if process.returncode:
                raise MusicError(f"The audio renderer exited with code {process.returncode}")
            if _count(receipt, "sample_rate") != 44100 or _count(receipt, "channels") != 2:
                raise MusicError("The audio renderer returned an unexpected PCM format")
            frames = _count(receipt, "frames")
            effects = _count(receipt, "effects")
            keysounds = _count(receipt, "keysounds")
            versions = (
                ("ksm-v2", _UPSTREAM_COMMIT),
                ("ksmaudio", _AUDIO_COMMIT),
                ("bass", _version(receipt, "bass_version")),
                ("bass_fx", _version(receipt, "bass_fx_version")),
            )
            if not output.is_file() or output.stat().st_size < 44:
                raise MusicError("The audio renderer did not produce its PCM output")
            _validate_pcm(output, frames)
            os.replace(output, request.destination)
        diagnostics = (
            Diagnostic(
                "AUDIO_RENDERED",
                Severity.INFO,
                Stage.MUSIC,
                f"Rendered {frames} stereo frames with {effects} effects and {keysounds} keysounds.",
                "audio.rendering",
            ),
        )
        return AudioRenderResult(
            ProcessedResource(request.destination, ()),
            diagnostics,
            versions,
            frames,
            effects,
            keysounds,
        )
