"""Audio command arguments and presentation."""

import argparse
from pathlib import Path

from ksm2sdvx.common.cli import print_diagnostics
from ksm2sdvx.music.application import convert_audio_file
from ksm2sdvx.music.models import S3vMusicSettings


class AudioArguments(argparse.Namespace):
    source: Path = Path()
    output: Path | None = None
    ffmpeg: str = "ffmpeg"
    target_lufs: float = -11.0
    true_peak_dbtp: float = -1.0
    preview_start_ms: int | None = None
    preview_duration_ms: int | None = None
    gain_db: float | None = None
    chart: Path | None = None
    audio_offset_ms: int | None = None
    audio_source_volume: float | None = None


def add_audio_arguments(parser: argparse.ArgumentParser) -> None:
    defaults = S3vMusicSettings()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("source", type=Path, nargs="?")
    source.add_argument("--chart", type=Path, help="Render this KSON chart's effects and keysounds")
    parser.add_argument("-o", "--output", type=Path, help="Output .s3v file")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--target-lufs", type=float, default=defaults.target_lufs)
    parser.add_argument("--true-peak-dbtp", type=float, default=defaults.true_peak_dbtp)
    parser.add_argument("--source-volume", type=float, dest="audio_source_volume")
    parser.add_argument(
        "--offset-ms",
        type=int,
        dest="audio_offset_ms",
        help="Positive trims the start; negative adds silence",
    )
    parser.add_argument("--preview-start-ms", type=int, help="Preview start in the original audio")
    parser.add_argument("--preview-duration-ms", type=int)
    parser.add_argument("--gain-db", type=float, help="Reuse an explicit gain, e.g. for a preview")


def run_audio(args: AudioArguments) -> int:
    result = convert_audio_file(
        args.source,
        output=args.output,
        ffmpeg=args.ffmpeg,
        settings=S3vMusicSettings(
            target_lufs=args.target_lufs,
            true_peak_dbtp=args.true_peak_dbtp,
            offset_ms=args.audio_offset_ms if args.audio_offset_ms is not None else 0,
            source_volume=args.audio_source_volume if args.audio_source_volume is not None else 1.0,
            preview_start_ms=args.preview_start_ms,
            preview_duration_ms=args.preview_duration_ms,
            gain_db=args.gain_db,
        ),
    )
    print_diagnostics(result.diagnostics)
    print(f"Audio: {result.resource.path}")
    if result.gain_db is not None:
        print(f"Gain: {result.gain_db:.2f} dB")
    if result.output_measurement is not None:
        print(f"Output loudness: {result.output_measurement.integrated_lufs:.2f} LUFS")
    return 0
