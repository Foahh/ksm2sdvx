"""Real chart instructions rendered by the installed native helper."""

import array
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest
from tests.conftest import document

from ksm2sdvx.chart import compile_chart_audio, parse_kson
from ksm2sdvx.music import AudioRenderRequest, AudioSource, NativeAudioRenderer, bundled_preset

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows x64 audio renderer")


@pytest.fixture
def ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is required for audio processing")
    return executable


def _music(path: Path, *, amplitude: int = 10000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(
            b"".join(
                struct.pack("<h", round(amplitude * math.sin(frame * 2 * math.pi * 730 / 48000)))
                for frame in range(96000)
            )
        )


def _pcm(path: Path, ffmpeg: str) -> array.array[float]:
    process = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    )
    samples = array.array("f")
    samples.frombytes(process.stdout)
    return samples


def test_compiled_effect_changes_audio_only_during_hold(tmp_path: Path, ffmpeg: str) -> None:
    source = tmp_path / "音源.wav"
    _music(source)
    dry = compile_chart_audio(parse_kson(document()).chart)
    wet = compile_chart_audio(
        parse_kson(
            document(
                note={"fx": [[[120, 240]], []]},
                audio={
                    "audio_effect": {
                        "fx": {
                            "def": [
                                ["crusher", {"type": "bitcrusher", "v": {"reduction": "16samples"}}]
                            ],
                            "long_event": {"crusher": [[120], []]},
                        }
                    }
                },
            )
        ).chart
    )
    renderer = NativeAudioRenderer(ffmpeg)
    original = renderer.render(
        AudioRenderRequest(dry, tmp_path / "dry.wav", AudioSource("main", source))
    )
    first = renderer.render(
        AudioRenderRequest(wet, tmp_path / "wet.wav", AudioSource("main", source))
    )
    second = renderer.render(
        AudioRenderRequest(wet, tmp_path / "repeat.wav", AudioSource("main", source))
    )
    assert first.frames == original.frames == 88200
    assert dict(first.versions)["bass"] == "2.4.18.3"
    assert first.processing_profile == "ksm-compressed-v1"
    assert first.saturated_samples == 0
    assert first.resource.path.read_bytes() == second.resource.path.read_bytes()
    dry_pcm = _pcm(original.resource.path, ffmpeg)
    wet_pcm = _pcm(first.resource.path, ffmpeg)
    start, end = 11025 * 2, 33075 * 2
    assert dry_pcm[:start] == wet_pcm[:start]
    assert dry_pcm[start:end] != wet_pcm[start:end]
    assert dry_pcm[end:] == wet_pcm[end:]


def test_bundled_keysound_mixes_with_authored_relative_gain(tmp_path: Path, ffmpeg: str) -> None:
    source = tmp_path / "music.wav"
    _music(source)
    chart = parse_kson(
        document(
            note={"fx": [[120], []]},
            audio={
                "bgm": {"vol": 0},
                "key_sound": {"fx": {"chip_event": {"clap": [[[120, {"vol": 0.5}]], []]}}},
            },
        )
    ).chart
    result = NativeAudioRenderer(ffmpeg).render(
        AudioRenderRequest(
            compile_chart_audio(chart),
            tmp_path / "mixed.wav",
            AudioSource("main", source),
            samples=(AudioSource("clap", bundled_preset("clap")),),
        )
    )
    samples = _pcm(result.resource.path, ffmpeg)
    assert result.keysounds == 1
    assert all(value == 0 for value in samples[: 11025 * 2])
    assert any(abs(value) > 0.001 for value in samples[11025 * 2 :])
    for name in ("clap", "clap_impact", "clap_punchy", "snare", "snare_lo"):
        assert bundled_preset(name).is_file()


def test_laser_boost_is_compressed_before_export(tmp_path: Path, ffmpeg: str) -> None:
    source = tmp_path / "music.wav"
    _music(source, amplitude=30000)
    dry_chart = parse_kson(document()).chart
    wet_chart = parse_kson(
        document(
            note={"laser": [[[0, [[0, 0.4], [960, 0.4]], 1]], []]},
            audio={
                "audio_effect": {
                    "laser": {
                        "peaking_filter_delay": 0,
                        "def": [
                            [
                                "peaking_filter",
                                {
                                    "type": "peaking_filter",
                                    "v": {"freq": "730Hz", "freq_max": "730Hz"},
                                },
                            ]
                        ],
                    }
                }
            },
        )
    ).chart
    renderer = NativeAudioRenderer(ffmpeg)
    outputs: list[array.array[float]] = []
    for name, chart in (("dry", dry_chart), ("wet", wet_chart)):
        result = renderer.render(
            AudioRenderRequest(
                compile_chart_audio(chart), tmp_path / f"{name}.wav", AudioSource("main", source)
            )
        )
        outputs.append(_pcm(result.resource.path, ffmpeg))
    dry_pcm, wet_pcm = outputs
    # Ignore the attack; a sustained resonant filter must not create an uncontrolled boost.
    dry_energy = sum(value * value for value in dry_pcm[44100:88200])
    wet_energy = sum(value * value for value in wet_pcm[44100:88200])
    assert 0 < 10 * math.log10(wet_energy / dry_energy) < 10
    assert max(abs(value) for value in wet_pcm) <= 1
    assert result.saturated_samples < result.frames * 2 * 0.01
