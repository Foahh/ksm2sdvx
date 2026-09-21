"""Contracts for audio processing and compressed file encoding."""

from pathlib import Path
from typing import Protocol

from ksm2sdvx.music.models import MusicRequest, MusicResult


class MusicProcessor[SettingsT](Protocol):
    def process(self, request: MusicRequest[SettingsT]) -> MusicResult:
        """Produce the requested file or raise Ksm2SdvxError; never return a skipped success."""
        ...


class S3vEncoder(Protocol):
    def encode(self, source: Path, destination: Path) -> None:
        """Encode 44.1 kHz 16-bit stereo WAV to WMA Professional in ASF."""
        ...
