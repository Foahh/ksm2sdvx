"""Regenerate the bundled silent FX chip bank using the Windows WMA encoder."""

import argparse
import os
import tempfile
import wave
from pathlib import Path

from ksm2sdvx.music._s3p import serialize_s3p
from ksm2sdvx.music._windows import WindowsWmaProEncoder
from ksm2sdvx.music.errors import MusicError


def generate_bank(destination: Path) -> None:
    """Encode 250 ms of stereo silence and pack fifteen identical sample slots."""
    encoder = WindowsWmaProEncoder()
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
    except (OSError, wave.Error) as exc:
        raise MusicError(f"Cannot write silent keysound bank: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "src/ksm2sdvx/music/assets/silent_keysounds.s3p",
    )
    args = parser.parse_args()
    try:
        generate_bank(Path(args.output))
    except MusicError as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
