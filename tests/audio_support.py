"""Synthetic ASF framing and a silent-input encoder double."""

import struct
import wave
from pathlib import Path

from ksm2sdvx.music._s3v import serialize_s3v
from ksm2sdvx.music.errors import MusicError


def asf_payload() -> bytes:
    header = bytearray(
        bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
        + struct.pack("<QI2B", 134, 1, 1, 2)
        + bytes.fromhex("a1dcab8c47a9cf118ee400c00c205365")
        + struct.pack("<Q", 104)
        + bytes(80)
    )
    payload = header + b"synthetic audio payload"
    struct.pack_into("<Q", payload, 70, len(payload))
    return bytes(payload)


class SilentS3vEncoder:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def encode(self, source: Path, destination: Path) -> None:
        self.calls += 1
        with wave.open(str(source), "rb") as pcm:
            assert (pcm.getnchannels(), pcm.getsampwidth(), pcm.getframerate()) == (2, 2, 44100)
            assert pcm.getnframes() == 11025
            assert pcm.readframes(pcm.getnframes()) == bytes(11025 * 4)
        if self.fail:
            raise MusicError("Sample encoding failed")
        destination.write_bytes(serialize_s3v(asf_payload()))
