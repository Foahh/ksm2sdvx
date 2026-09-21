"""Installed ksm2sdvx command dispatcher."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ksm2sdvx.chart import DEFAULT_PROFILE
from ksm2sdvx.chart.cli import (
    ChartArguments,
    add_conversion_arguments,
    conversion_options,
    run_chart,
)
from ksm2sdvx.common.cli import print_diagnostics
from ksm2sdvx.common.errors import Ksm2SdvxError
from ksm2sdvx.common.types import json_ready
from ksm2sdvx.jacket.cli import JacketArguments, add_jacket_arguments, run_jacket
from ksm2sdvx.music.cli import AudioArguments, add_audio_arguments, run_audio
from ksm2sdvx.pipeline import SourcePackage, inspect_package
from ksm2sdvx.pipeline.audio import convert_chart_audio_file
from ksm2sdvx.pipeline.build import build_package
from ksm2sdvx.pipeline.config import load_package_config
from ksm2sdvx.pipeline.report import inspection_to_dict


class Arguments(ChartArguments, AudioArguments, JacketArguments):
    command: str = ""
    sources: tuple[Path, ...] = ()
    root: Path = Path()
    manifest: Path = Path()
    game_data: Path = Path()
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksm2sdvx", description="Convert charts and build LayeredFS song packages."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chart = commands.add_parser("chart", help="Write a VOX chart and conversion report")
    chart.add_argument("source", type=Path)
    chart.add_argument("-o", "--output", type=Path)
    audio = commands.add_parser("audio", help="Normalize audio and write a WMA Professional .s3v")
    add_audio_arguments(audio)
    audio.add_argument("--strict", action="store_true", help="Reject omitted audio features")
    jacket = commands.add_parser("jacket", help="Resize artwork and write an arcade RGB PNG")
    add_jacket_arguments(jacket)
    inspect = commands.add_parser("inspect", help="Inspect charts and resources as read-only JSON")
    inspect.add_argument("sources", type=Path, nargs="+")
    inspect.add_argument("--root", type=Path, required=True)
    package = commands.add_parser("package", help="Build a new-song data_mods package")
    package.add_argument("manifest", type=Path)
    package.add_argument(
        "--game-data",
        type=Path,
        required=True,
        help="Reference data directory containing others/music_db.xml and graphics",
    )
    package.add_argument("-o", "--output", type=Path, help="New mod directory (must not exist)")
    package.add_argument("--ffmpeg", default="ffmpeg")
    package.add_argument("--ffprobe", default="ffprobe")
    for command in (chart, inspect, package):
        add_conversion_arguments(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv, namespace=Arguments())
    if (
        args.command == "audio"
        and args.chart is not None
        and any(
            value is not None
            for value in (
                args.audio_offset_ms,
                args.audio_source_volume,
                args.preview_start_ms,
                args.preview_duration_ms,
            )
        )
    ):
        parser.error(
            "--chart uses KSON timing and volume; omit raw-audio timing and volume options"
        )
    try:
        if args.command == "audio":
            if args.chart is not None:
                rendered = convert_chart_audio_file(
                    args.chart,
                    output=args.output,
                    strict=args.strict,
                    target_lufs=args.target_lufs,
                    true_peak_dbtp=args.true_peak_dbtp,
                    gain_db=args.gain_db,
                    ffmpeg=args.ffmpeg,
                )
                print_diagnostics(rendered.diagnostics)
                print(f"Audio: {rendered.destination}\nReport: {rendered.report_path}")
                return 0
            return run_audio(args)
        if args.command == "jacket":
            return run_jacket(args)
        if args.command == "package":
            config = load_package_config(args.manifest)
            result = build_package(
                config,
                game_data=args.game_data,
                destination=args.output or Path("output/data_mods") / config.name,
                options=conversion_options(args),
                profile=DEFAULT_PROFILE,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
            print_diagnostics(result.diagnostics)
            print(f"Package: {result.destination}\nFiles: {len(result.files)}")
            return 0
        if args.command == "inspect":
            inspection = inspect_package(
                SourcePackage(args.root, tuple(args.sources)),
                options=conversion_options(args),
                profile=DEFAULT_PROFILE,
            )
            print(
                json.dumps(
                    json_ready(inspection_to_dict(inspection)),
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            return 0 if inspection.valid else 1
        return run_chart(args)
    except Ksm2SdvxError as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1
