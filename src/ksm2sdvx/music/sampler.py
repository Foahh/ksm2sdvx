"""Bundled silent native keysounds for samples already rendered into music."""

import os
import tempfile
from importlib.resources import files
from pathlib import Path

from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.resources.models import ProcessedResource

SILENT_KEYSOUND_SAMPLE = 2


def write_silent_keysound_bank(destination: Path) -> ProcessedResource:
    """Copy the bundled bank atomically under a difficulty's sampler filename."""
    try:
        data = files("ksm2sdvx.music").joinpath("assets/silent_keysounds.s3p").read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".ksm2sdvx-sampler-", dir=destination.parent
        ) as temp:
            bank = Path(temp) / "sampler.s3p"
            bank.write_bytes(data)
            os.replace(bank, destination)
        return ProcessedResource(destination, ())
    except OSError as exc:
        raise MusicError(f"Cannot copy bundled silent keysound bank: {exc}") from exc
