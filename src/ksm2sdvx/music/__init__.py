"""Public music processing contracts."""

from ksm2sdvx.music.interfaces import MusicProcessor
from ksm2sdvx.music.models import MusicRequest, MusicResult

__all__ = ["MusicProcessor", "MusicRequest", "MusicResult"]
