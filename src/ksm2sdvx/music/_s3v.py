"""S3V framing around a complete ASF audio payload."""

import struct

from ksm2sdvx.music.errors import MusicError

_ASF_HEADER = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
_ASF_FILE_PROPERTIES = bytes.fromhex("a1dcab8c47a9cf118ee400c00c205365")
_FOOTER_SIZE = 32


def _validate_asf(payload: bytes) -> None:
    if len(payload) < 30 or payload[:16] != _ASF_HEADER:
        raise MusicError("S3V requires a complete ASF audio payload")
    header_size, object_count = struct.unpack_from("<QI", payload, 16)
    if not 30 <= header_size <= len(payload):
        raise MusicError("ASF header size is invalid")
    position = 30
    file_properties = 0
    for _ in range(object_count):
        if position + 24 > header_size:
            raise MusicError("ASF header object is truncated")
        size = struct.unpack_from("<Q", payload, position + 16)[0]
        if size < 24 or position + size > header_size:
            raise MusicError("ASF header object size is invalid")
        if payload[position : position + 16] == _ASF_FILE_PROPERTIES:
            if size < 104:
                raise MusicError("ASF file properties are truncated")
            declared_size = struct.unpack_from("<Q", payload, position + 40)[0]
            if declared_size != len(payload):
                raise MusicError("ASF file size does not match its payload")
            file_properties += 1
        position += size
    if position != header_size or file_properties != 1:
        raise MusicError("ASF requires one file-properties object and a complete header")


def serialize_s3v(payload: bytes) -> bytes:
    """Append the required footer with no extra playback gain or ancillary metadata."""
    if len(payload) > 0xFFFFFFFF:
        raise MusicError("S3V audio payload exceeds its 32-bit size field")
    _validate_asf(payload)
    return payload + struct.pack("<4sII20x", b"S3V0", _FOOTER_SIZE, len(payload))


def validate_s3v(data: bytes) -> None:
    """Check S3V framing and ASF lengths; codec decoding is verified separately."""
    if len(data) < _FOOTER_SIZE or data[-_FOOTER_SIZE:-28] != b"S3V0":
        raise MusicError("S3V audio is missing its S3V0 footer")
    footer_size, payload_size = struct.unpack_from("<II", data, len(data) - 28)
    if footer_size != _FOOTER_SIZE or payload_size != len(data) - _FOOTER_SIZE:
        raise MusicError("S3V footer sizes do not match its audio payload")
    _validate_asf(data[:-_FOOTER_SIZE])
