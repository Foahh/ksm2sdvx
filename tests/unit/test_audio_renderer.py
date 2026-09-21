"""Failure isolation and validation at the native audio process boundary."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from ksm2sdvx.common.types import JsonValue
from ksm2sdvx.music import renderer
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.render_models import AudioRenderRequest, AudioSource


@dataclass(frozen=True, slots=True)
class Program:
    sample_rate: int = 44100
    duration_frames: int = 44100
    offset_frames: int = 0
    bgm_volume: float = 1.0

    def to_dict(self) -> dict[str, JsonValue]:
        return {}


def _request(tmp_path: Path, program: Program | None = None) -> AudioRenderRequest:
    source = tmp_path / "input.wav"
    source.write_bytes(b"source")
    return AudioRenderRequest(
        program or Program(), tmp_path / "output.wav", AudioSource("main", source)
    )


@pytest.mark.parametrize(
    "program",
    [Program(sample_rate=48000), Program(duration_frames=-1), Program(bgm_volume=float("nan"))],
)
def test_invalid_render_request_fails_before_creating_output(
    tmp_path: Path, program: Program
) -> None:
    request = _request(tmp_path, program)
    with pytest.raises(MusicError):
        renderer.NativeAudioRenderer().render(request)
    assert not request.destination.exists()


def test_renderer_never_overwrites_a_source(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    source.write_bytes(b"original")
    request = AudioRenderRequest(Program(), source, AudioSource("main", source))
    with pytest.raises(MusicError, match="overwrite"):
        renderer.NativeAudioRenderer().render(request)
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize(
    ("stdout", "code", "message"),
    [
        ("", -1, "exited with code"),
        ("not JSON", 0, "invalid JSON"),
        ('{"protocol_version":true}', 0, "protocol version"),
        ('{"protocol_version":2}', 0, "protocol version"),
        (
            '{"protocol_version":1,"error":{"code":"INVALID_PARAMETER","message":"Bad mix"}}',
            1,
            "INVALID_PARAMETER",
        ),
        (
            '{"protocol_version":1,"sample_rate":44100,"channels":2,"frames":true}',
            0,
            "invalid frames",
        ),
        (
            '{"protocol_version":1,"sample_rate":44100,"channels":2,"frames":1,'
            '"effects":0,"keysounds":0,"bass_version":"2.4.18.3",'
            '"bass_fx_version":"2.4.12.6","processing_profile":"ksm-compressed-v1",'
            '"saturated_samples":0}',
            0,
            "invalid WAV",
        ),
    ],
)
def test_failed_native_response_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, code: int, message: str
) -> None:
    request = _request(tmp_path)
    request.destination.write_bytes(b"previous output")

    class PreparedRenderer(renderer.NativeAudioRenderer):
        def _decode(self, source: Path, destination: Path) -> None:
            destination.write_bytes(source.read_bytes())

    def run(arguments: list[str], *, label: str) -> subprocess.CompletedProcess[str]:
        Path(arguments[-1]).write_bytes(b"partial output" * 8)
        return subprocess.CompletedProcess(arguments, code, stdout, "native failure")

    monkeypatch.setattr(renderer, "_renderer_executable", lambda: tmp_path / "renderer.exe")
    monkeypatch.setattr(renderer, "_run", run)
    with pytest.raises(MusicError, match=message):
        PreparedRenderer().render(request)
    assert request.destination.read_bytes() == b"previous output"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.wav", "output.wav"]


def test_unknown_preset_cannot_resolve_arbitrary_package_files() -> None:
    with pytest.raises(MusicError, match="Unknown built-in"):
        renderer.bundled_preset("../bass")


def test_unavailable_platform_reports_requirement_before_preset_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer.sys, "platform", "linux")
    with pytest.raises(MusicError, match="requires Windows x64"):
        renderer.bundled_preset("clap")
