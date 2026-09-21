"""Generate silent native keysounds for charts whose samples are baked into music."""

import os
import tempfile
import wave
from pathlib import Path

from ksm2sdvx.music._s3p import serialize_s3p
from ksm2sdvx.music._windows import WindowsWmaProEncoder
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.interfaces import S3vEncoder
from ksm2sdvx.resources.models import ProcessedResource

SILENT_KEYSOUND_SAMPLE = 2


def write_silent_keysound_bank(
    destination: Path, *, encoder: S3vEncoder | None = None
) -> ProcessedResource:
    """Write fifteen silent sample slots without loudness normalization.

    The per-chart general sampler replaces the native FX chip bank. Laser slams
    use a separate bank. The package must include this file whenever its VOX
    chips reference SILENT_KEYSOUND_SAMPLE after rendering.
    """
    encoder = encoder if encoder is not None else WindowsWmaProEncoder()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".ksm2sdvx-sampler-", dir=destination.parent
        ) as temp:
            workspace = Path(temp)
            pcm = workspace / "silence.wav"
            with wave.open(str(pcm), "wb") as audio:
                audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(bytes(11025 * 4))
            encoded = workspace / "silence.s3v"
            encoder.encode(pcm, encoded)
            bank = workspace / "sampler.s3p"
            bank.write_bytes(serialize_s3p((encoded.read_bytes(),) * 15))
            os.replace(bank, destination)
        return ProcessedResource(destination, ())
    except (OSError, wave.Error) as exc:
        raise MusicError(f"Cannot write silent keysound bank: {exc}") from exc
