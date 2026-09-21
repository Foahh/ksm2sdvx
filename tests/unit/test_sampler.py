import struct
import zlib
from pathlib import Path

import pytest
from tests.audio_support import SilentS3vEncoder, asf_payload

from ksm2sdvx.music._s3p import serialize_s3p
from ksm2sdvx.music._s3v import serialize_s3v
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.sampler import SILENT_KEYSOUND_SAMPLE, write_silent_keysound_bank


def test_bank_indexes_header_prefixed_samples_and_checksum() -> None:
    asf = asf_payload()
    data = serialize_s3p((serialize_s3v(asf),) * 15)
    assert struct.unpack_from("<4sI", data) == (b"S3P0", 15)
    assert 0 < SILENT_KEYSOUND_SAMPLE < 15
    previous_end = 128
    for i in range(15):
        offset, size = struct.unpack_from("<II", data, 8 + i * 8)
        assert offset == previous_end and size % 4 == 0
        assert struct.unpack_from("<4sII", data, offset) == (b"S3V0", 32, len(asf))
        assert data[offset + 12 : offset + 32] == bytes(20)
        assert data[offset + 32 : offset + 32 + len(asf)] == asf
        assert not any(data[offset + 32 + len(asf) : offset + size])
        previous_end = offset + size
    assert previous_end == len(data) - 4
    assert struct.unpack_from("<I", data, previous_end)[0] == zlib.crc32(data[:-4])


@pytest.mark.parametrize("samples", [(), (b"",), (b"invalid",)])
def test_invalid_sample_bank_is_rejected(samples: tuple[bytes, ...]) -> None:
    with pytest.raises(MusicError):
        serialize_s3p(samples)


@pytest.mark.parametrize("fail", [False, True])
def test_silent_bank_encoding_is_atomic(tmp_path: Path, fail: bool) -> None:
    destination = tmp_path / "bank.s3p"
    destination.write_bytes(b"existing")
    encoder = SilentS3vEncoder(fail=fail)
    if fail:
        with pytest.raises(MusicError, match="Sample encoding failed"):
            write_silent_keysound_bank(destination, encoder=encoder)
        assert destination.read_bytes() == b"existing"
    else:
        result = write_silent_keysound_bank(destination, encoder=encoder)
        assert result.path == destination
        assert destination.read_bytes().startswith(b"S3P0")
    assert encoder.calls == 1
    assert tuple(tmp_path.iterdir()) == (destination,)
