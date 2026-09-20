"""Contract for a music processor; no processor is installed by default."""

from typing import Protocol

from ksm2sdvx.music.models import MusicRequest, MusicResult


class MusicProcessor[SettingsT](Protocol):
    def process(self, request: MusicRequest[SettingsT]) -> MusicResult:
        """Produce the requested file or raise Ksm2SdvxError; never return a skipped success."""
        ...
