"""Argument and presentation adapters for chart conversion."""

import argparse
from pathlib import Path

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions
from ksm2sdvx.chart.application import convert_chart_file
from ksm2sdvx.common.cli import print_diagnostics


class ChartArguments(argparse.Namespace):
    source: Path = Path()
    output: Path | None = None
    strict: bool = False
    curve_step: int = 15


def add_conversion_arguments(parser: argparse.ArgumentParser) -> None:
    defaults = ConversionOptions()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Reject omitted features; supported approximations remain allowed",
    )
    parser.add_argument("--curve-step", type=int, default=defaults.curve_step)


def conversion_options(args: ChartArguments) -> ConversionOptions:
    return ConversionOptions(
        args.curve_step,
        args.strict,
    )


def run_chart(args: ChartArguments) -> int:
    result = convert_chart_file(
        args.source,
        output=args.output,
        options=conversion_options(args),
        profile=DEFAULT_PROFILE,
    )
    print_diagnostics(result.report.diagnostics)
    print(f"VOX: {result.destination}\nReport: {result.report_path}")
    return 0
