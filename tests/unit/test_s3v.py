"""S3V framing independent of the Windows audio codec."""

import struct

import pytest
from tests.audio_support import asf_payload

from ksm2sdvx.music._s3v import serialize_s3v, validate_s3v
from ksm2sdvx.music.errors import MusicError


def test_footer_preserves_asf_payload_and_adds_no_gain() -> None:
    payload = asf_payload()
    result = serialize_s3v(payload)
    assert result[:-32] == payload
    assert result[-32:-28] == b"S3V0"
    assert struct.unpack("<II", result[-28:-20]) == (32, len(payload))
    assert result[-20:] == bytes(20)
    validate_s3v(result)


def test_plain_asf_is_not_s3v() -> None:
    with pytest.raises(MusicError, match="footer"):
        validate_s3v(asf_payload())


@pytest.mark.parametrize("position,value", [(0, 0), (16, 255), (24, 2), (46, 0), (70, 0)])
def test_invalid_asf_is_rejected(position: int, value: int) -> None:
    payload = bytearray(asf_payload())
    payload[position] = value
    with pytest.raises(MusicError, match="ASF"):
        serialize_s3v(bytes(payload))


@pytest.mark.parametrize("position,value", [(-32, 0), (-28, 31), (-24, 0)])
def test_invalid_footer_is_rejected(position: int, value: int) -> None:
    payload = bytearray(serialize_s3v(asf_payload()))
    payload[position] = value
    with pytest.raises(MusicError, match="S3V"):
        validate_s3v(bytes(payload))


def test_truncated_or_already_wrapped_payload_is_rejected() -> None:
    with pytest.raises(MusicError):
        serialize_s3v(b"")
    with pytest.raises(MusicError, match="file size"):
        serialize_s3v(asf_payload()[:-1])
    with pytest.raises(MusicError, match="file size"):
        serialize_s3v(serialize_s3v(asf_payload()))
