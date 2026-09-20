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
from ksm2sdvx.common.errors import Ksm2SdvxError
from ksm2sdvx.common.types import json_ready
from ksm2sdvx.pipeline import SourcePackage, inspect_package
from ksm2sdvx.pipeline.report import inspection_to_dict


class Arguments(ChartArguments):
    command: str = ""
    sources: tuple[Path, ...] = ()
    root: Path = Path()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksm2sdvx", description="Convert charts and inspect source packages."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chart = commands.add_parser("chart", help="Write a VOX chart and conversion report")
    chart.add_argument("source", type=Path)
    chart.add_argument("-o", "--output", type=Path)
    inspect = commands.add_parser("inspect", help="Inspect charts and resources as read-only JSON")
    inspect.add_argument("sources", type=Path, nargs="+")
    inspect.add_argument("--root", type=Path, required=True)
    for command in (chart, inspect):
        add_conversion_arguments(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv, namespace=Arguments())
    try:
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
