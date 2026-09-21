import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from ksm2sdvx.jacket import (
    FfmpegJacketProcessor,
    JacketError,
    JacketRequest,
    JacketSettings,
    JacketSize,
)
from ksm2sdvx.resources import ResourceRecord, ResourceUse


def _png(width: int, height: int, pixels: bytes, *, alpha: bool = False) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
        )

    channels = 4 if alpha else 3
    rows = b"".join(
        b"\0" + pixels[y * width * channels : (y + 1) * width * channels] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _source(path: Path) -> ResourceRecord:
    return ResourceRecord(
        path.name,
        path,
        preset=False,
        exists=True,
        uses=(ResourceUse(path.parent / "chart.kson", "jacket", "/meta/jacket_filename"),),
    )


@pytest.fixture
def processor() -> FfmpegJacketProcessor:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("Jacket integration requires FFmpeg and FFprobe.")
    return FfmpegJacketProcessor(ffmpeg=ffmpeg, ffprobe=ffprobe)


def _pixels(processor: FfmpegJacketProcessor, path: Path) -> bytes:
    return subprocess.run(
        [
            processor.ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


@pytest.mark.parametrize("size", tuple(JacketSize))
def test_sizes_rgb_and_containment(
    tmp_path: Path, processor: FfmpegJacketProcessor, size: JacketSize
) -> None:
    source = tmp_path / "source with spaces.png"
    source.write_bytes(_png(12, 8, bytes((255, 0, 0)) * 96))
    output = tmp_path / "nested" / "jacket.png"
    request = JacketRequest(_source(source), output, JacketSettings(size=size))
    result = processor.process(request)

    header = output.read_bytes()[:33]
    assert struct.unpack_from(">II", header, 16) == (int(size), int(size))
    assert header[24:29] == bytes((8, 2, 0, 0, 0))
    pixels = _pixels(processor, output)
    assert pixels[:3] == b"\0\0\0"
    center = ((int(size) // 2) * int(size) + int(size) // 2) * 3
    assert pixels[center : center + 3] == bytes((255, 0, 0))
    assert result.resource.path == output
    assert result.resource.uses == request.source.uses
    assert [item.code for item in result.diagnostics] == ["JACKET_ASPECT_FIT"]
    assert tuple(output.parent.iterdir()) == (output,)


def test_alpha_is_composited_on_black(tmp_path: Path, processor: FfmpegJacketProcessor) -> None:
    source = tmp_path / "transparent.png"
    source.write_bytes(_png(4, 4, bytes((255, 0, 0, 128)) * 16, alpha=True))
    output = tmp_path / "jacket.png"
    result = processor.process(JacketRequest(_source(source), output, JacketSettings()))
    pixels = _pixels(processor, output)
    assert 127 <= pixels[0] <= 129
    assert pixels[1:3] == b"\0\0"
    assert not result.diagnostics


def test_bad_input_does_not_replace_output(
    tmp_path: Path, processor: FfmpegJacketProcessor
) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(b"not an image")
    output = tmp_path / "jacket.png"
    output.write_bytes(b"existing jacket")
    with pytest.raises(JacketError):
        processor.process(JacketRequest(_source(source), output, JacketSettings()))
    assert output.read_bytes() == b"existing jacket"
    assert {path.name for path in tmp_path.iterdir()} == {"broken.png", "jacket.png"}


def test_invalid_tool_output_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid_png(command: list[str], timeout: float) -> bytes:
        return b"4,4" if command[0] == "ffprobe" else b"not a PNG"

    monkeypatch.setattr("ksm2sdvx.jacket.processor._run", invalid_png)
    source = tmp_path / "source.png"
    source.write_bytes(_png(4, 4, bytes((255, 0, 0)) * 16))
    output = tmp_path / "jacket.png"
    with pytest.raises(JacketError, match="complete PNG"):
        FfmpegJacketProcessor().process(JacketRequest(_source(source), output, JacketSettings()))
    assert not output.exists()


def test_missing_tool_and_unsafe_destinations(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png(4, 4, bytes((255, 0, 0)) * 16))
    processor = FfmpegJacketProcessor(ffprobe=str(tmp_path / "absent-tool"))
    with pytest.raises(JacketError, match="Could not run"):
        processor.process(JacketRequest(_source(source), tmp_path / "jacket.png", JacketSettings()))
    with pytest.raises(JacketError, match="overwrite"):
        processor.process(JacketRequest(_source(source), source, JacketSettings()))
    with pytest.raises(JacketError, match="extension"):
        processor.process(JacketRequest(_source(source), tmp_path / "output.jpg", JacketSettings()))
    assert {path.name for path in tmp_path.iterdir()} == {"source.png"}
