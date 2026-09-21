"""S3P sample banks with indexed, header-prefixed S3V entries."""

import struct
import zlib

from ksm2sdvx.music._s3v import validate_s3v
from ksm2sdvx.music.errors import MusicError


def serialize_s3p(samples: tuple[bytes, ...]) -> bytes:
    """Pack standalone S3V files, moving each footer before its ASF payload."""
    if not samples:
        raise MusicError("A sample bank requires at least one sample")
    offset = 8 + 8 * len(samples)
    index = bytearray()
    entries = bytearray()
    for sample in samples:
        validate_s3v(sample)
        entry = sample[-32:] + sample[:-32]
        entry += bytes(-len(entry) % 4)
        if offset + len(entry) + 4 > 0xFFFFFFFF:
            raise MusicError("Sample bank exceeds its 32-bit size fields")
        index.extend(struct.pack("<II", offset, len(entry)))
        entries.extend(entry)
        offset += len(entry)
    bank = struct.pack("<4sI", b"S3P0", len(samples)) + index + entries
    return bank + struct.pack("<I", zlib.crc32(bank))
