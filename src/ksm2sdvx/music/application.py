"""Standalone audio file conversion."""

from pathlib import Path

from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.models import MusicRequest, MusicResult, S3vMusicSettings
from ksm2sdvx.music.processor import FfmpegMusicProcessor
from ksm2sdvx.resources.models import ResourceRecord, ResourceUse


def convert_audio_file(
    source: Path,
    *,
    output: Path | None = None,
    settings: S3vMusicSettings | None = None,
    ffmpeg: str = "ffmpeg",
) -> MusicResult:
    try:
        settings = settings if settings is not None else S3vMusicSettings()
        source = source.resolve()
        suffix = "_pre" if settings.preview_start_ms is not None else ""
        destination = output or Path("output") / f"{source.stem}{suffix}.s3v"
        if settings.preview_start_ms is not None and settings.offset_ms != 0:
            raise MusicError("Preview timing uses the original audio; offset_ms must be zero")
        resource = ResourceRecord(
            source.name, source, False, source.is_file(), (ResourceUse(source, "music", ""),)
        )
        return FfmpegMusicProcessor(ffmpeg).process(MusicRequest(resource, destination, settings))
    except OSError as exc:
        raise MusicError(f"Audio filesystem operation failed: {exc}") from exc
