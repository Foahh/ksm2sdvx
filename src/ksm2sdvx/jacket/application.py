"""Standalone jacket file conversion."""

from pathlib import Path

from ksm2sdvx.jacket.errors import JacketError
from ksm2sdvx.jacket.models import JacketRequest, JacketResult, JacketSettings
from ksm2sdvx.jacket.processor import FfmpegJacketProcessor
from ksm2sdvx.resources.models import ResourceRecord, ResourceUse


def convert_jacket_file(
    source: Path,
    *,
    output: Path | None = None,
    settings: JacketSettings | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> JacketResult:
    try:
        settings = settings if settings is not None else JacketSettings()
        source = source.resolve()
        destination = output or Path("output") / f"{source.stem}_{int(settings.size)}.png"
        resource = ResourceRecord(
            source.name, source, False, source.is_file(), (ResourceUse(source, "jacket", ""),)
        )
        return FfmpegJacketProcessor(ffmpeg=ffmpeg, ffprobe=ffprobe).process(
            JacketRequest(resource, destination, settings)
        )
    except OSError as exc:
        raise JacketError(f"Jacket filesystem operation failed: {exc}") from exc
