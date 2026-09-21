import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from ksm2sdvx.music.sampler import SILENT_KEYSOUND_SAMPLE, write_silent_keysound_bank


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows WMA Professional encoder")
def test_encoded_native_keysound_decodes_to_silence(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to verify the compressed sample")
    result = write_silent_keysound_bank(tmp_path / "general_sampler_5m.s3p")
    data = result.path.read_bytes()
    offset, size = struct.unpack_from("<II", data, 8 + SILENT_KEYSOUND_SAMPLE * 8)
    magic, header_size, payload_size = struct.unpack_from("<4sII", data, offset)
    assert magic == b"S3V0" and header_size == 32 and size >= 32 + payload_size
    sample = data[offset + header_size : offset + header_size + payload_size]
    for i in range(15):
        other, _ = struct.unpack_from("<II", data, 8 + i * 8)
        assert data[other + 32 : other + 32 + payload_size] == sample
    audio = tmp_path / "sample.wma"
    audio.write_bytes(sample)
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(audio), "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    assert len(decoded) >= 11025 * 2 * 4
    assert all(value == 0.0 for (value,) in struct.iter_unpack("<f", decoded))
