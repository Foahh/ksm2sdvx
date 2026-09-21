"""Produce square RGB PNG jackets with an explicitly selected FFmpeg executable."""

import math
import os
import re
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from ksm2sdvx.jacket.errors import JacketError
from ksm2sdvx.jacket.models import JacketRequest, JacketResult, JacketSettings
from ksm2sdvx.resources.models import ProcessedResource

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _run(command: list[str], timeout: float) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise JacketError(f"Jacket processing exceeded {timeout:g} seconds.") from exc
    except OSError as exc:
        raise JacketError(f"Could not run {command[0]}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise JacketError(f"Jacket processing failed: {detail or 'media tool returned an error'}")
    return result.stdout


def _filters(settings: JacketSettings) -> str:
    size = int(settings.size)
    filters = [
        "format=rgba,split[art][background];"
        "[background]lutrgb=r=0:g=0:b=0:a=255[black];"
        "[black][art]overlay=format=rgb:alpha=straight",
        "format=rgb24",
        f"scale={size}:{size}:force_original_aspect_ratio=decrease:flags=lanczos",
        f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]
    return ",".join(filters)


def _validate_png(data: bytes, size: int) -> None:
    if (
        len(data) < 45
        or not data.startswith(_PNG_SIGNATURE + b"\x00\x00\x00\rIHDR")
        or not data.endswith(_PNG_END)
    ):
        raise JacketError("The media tool did not produce a complete PNG image.")
    width, height = struct.unpack_from(">II", data, 16)
    if (width, height) != (size, size) or data[24:29] != bytes((8, 2, 0, 0, 0)):
        raise JacketError(f"The media tool must produce a {size}×{size} 8-bit RGB PNG.")
    expected_crc = int.from_bytes(data[29:33], "big")
    if zlib.crc32(data[12:29]) != expected_crc:
        raise JacketError("The media tool produced an invalid PNG header.")


def _write_png(destination: Path, data: bytes) -> None:
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix=".ksm2sdvx-", suffix=".png", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    except OSError as exc:
        raise JacketError(f"Could not write jacket {destination}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FfmpegJacketProcessor:
    """Decode the first image, resize it, and atomically publish a validated PNG."""

    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if not self.ffmpeg or not self.ffprobe:
            raise JacketError("FFmpeg and FFprobe executable names must not be empty.")
        if isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise JacketError("Jacket processing timeout must be finite and positive.")

    def process(self, request: JacketRequest[JacketSettings]) -> JacketResult:
        source = request.source.resolved_path
        if request.source.preset or source is None:
            raise JacketError("A jacket requires a source image file; presets are not supported.")
        if not source.is_file():
            raise JacketError(f"Jacket source is not a file: {source}")
        destination = request.destination
        if destination.suffix.lower() != ".png":
            raise JacketError("Jacket output must use the .png extension.")
        try:
            source = source.resolve(strict=True)
            if source == destination.resolve():
                raise JacketError("Jacket output must not overwrite its source image.")
        except OSError as exc:
            raise JacketError(f"Could not resolve jacket paths: {exc}") from exc

        dimensions = (
            _run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=p=0",
                    str(source),
                ],
                self.timeout,
            )
            .decode("ascii", errors="replace")
            .strip()
        )
        match = re.fullmatch(r"([1-9][0-9]*),([1-9][0-9]*)", dimensions)
        if match is None:
            raise JacketError("Could not determine the source image dimensions.")
        data = _run(
            [
                self.ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                _filters(request.settings),
                "-pix_fmt",
                "rgb24",
                "-c:v",
                "png",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            self.timeout,
        )
        _validate_png(data, int(request.settings.size))
        _write_png(destination, data)
        return JacketResult(ProcessedResource(destination, request.source.uses))
