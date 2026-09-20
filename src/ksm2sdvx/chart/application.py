"""Chart file conversion and staged VOX/report output."""

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from ksm2sdvx.chart import ConversionOptions, VoxProfile, convert_chart, load_kson, serialize_vox
from ksm2sdvx.chart.conversion.report import ConversionReport
from ksm2sdvx.common.errors import OutputError
from ksm2sdvx.common.types import json_ready


@dataclass(frozen=True, slots=True)
class ChartOutput:
    destination: Path
    report_path: Path
    report: ConversionReport


def convert_chart_file(
    source: Path,
    *,
    output: Path | None = None,
    options: ConversionOptions,
    profile: VoxProfile,
) -> ChartOutput:
    options.validate()
    profile.validate()
    parsed = load_kson(source)
    result = convert_chart(parsed.chart, options=options, profile=profile)
    report = replace(
        result.report,
        diagnostics=tuple(
            replace(d, source_path=str(source))
            for d in (*parsed.diagnostics, *result.report.diagnostics)
        ),
    )
    destination = output if output is not None else Path("output") / (source.stem + ".vox")
    if destination.suffix.lower() != ".vox":
        raise OutputError("Chart output must have a .vox extension")
    report_path = destination.with_suffix(".report.json")
    try:
        if source.resolve() in (destination.resolve(), report_path.resolve()):
            raise OutputError("Output would overwrite the source chart")
    except (OSError, ValueError) as exc:
        raise OutputError(f"Cannot resolve output: {exc}") from exc
    write_chart_files(
        destination,
        serialize_vox(result.chart),
        json.dumps(json_ready(report.to_dict()), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
    )
    return ChartOutput(destination, report_path, report)


def write_chart_files(destination: Path, vox_text: str, report_text: str) -> None:
    """Stage both files before replacing either; each replacement is atomic.

    A filesystem cannot atomically replace the pair. If the second replacement
    fails, report the failure rather than claim a successful conversion.
    """
    staged: list[tuple[Path, Path]] = []
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        for target, text in (
            (destination, vox_text),
            (destination.with_suffix(".report.json"), report_text),
        ):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=".ksm2sdvx-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                staged.append((temporary, target))
                handle.write(text)
            if target.is_dir():
                raise OutputError(f"Output destination is a directory: {target}")
        for temporary, target in staged:
            os.replace(temporary, target)
    except (OSError, UnicodeError) as exc:
        raise OutputError(str(exc)) from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
