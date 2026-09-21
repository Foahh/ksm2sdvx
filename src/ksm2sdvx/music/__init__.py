"""Audio processing, loudness normalization, and S3V encoding."""

from ksm2sdvx.music._windows import WindowsWmaProEncoder
from ksm2sdvx.music.application import convert_audio_file
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.interfaces import MusicProcessor, S3vEncoder
from ksm2sdvx.music.models import LoudnessMeasurement, MusicRequest, MusicResult, S3vMusicSettings
from ksm2sdvx.music.processor import FfmpegMusicProcessor, normalization_gain
from ksm2sdvx.music.render_models import (
    AudioRenderer,
    AudioRenderRequest,
    AudioRenderResult,
    AudioSource,
    RenderProgram,
)
from ksm2sdvx.music.renderer import NativeAudioRenderer, bundled_preset

__all__ = [
    "AudioRenderer",
    "AudioRenderRequest",
    "AudioRenderResult",
    "AudioSource",
    "FfmpegMusicProcessor",
    "LoudnessMeasurement",
    "MusicError",
    "MusicProcessor",
    "MusicRequest",
    "MusicResult",
    "NativeAudioRenderer",
    "RenderProgram",
    "S3vEncoder",
    "S3vMusicSettings",
    "WindowsWmaProEncoder",
    "normalization_gain",
    "convert_audio_file",
    "bundled_preset",
]
