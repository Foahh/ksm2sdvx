"""Jacket command arguments and presentation."""

import argparse
from pathlib import Path

from ksm2sdvx.common.cli import print_diagnostics
from ksm2sdvx.jacket.application import convert_jacket_file
from ksm2sdvx.jacket.models import JacketSettings, JacketSize


class JacketArguments(argparse.Namespace):
    source: Path = Path()
    output: Path | None = None
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    size: int = int(JacketSize.STANDARD)


def add_jacket_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="Output RGB PNG file")
    parser.add_argument(
        "--size",
        type=int,
        choices=[int(size) for size in JacketSize],
        default=300,
        help="108 small, 128 selector, 300 standard, 676 large",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")


def run_jacket(args: JacketArguments) -> int:
    result = convert_jacket_file(
        args.source,
        output=args.output,
        settings=JacketSettings(JacketSize(args.size)),
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print_diagnostics(result.diagnostics)
    print(f"Jacket: {result.resource.path}")
    return 0
