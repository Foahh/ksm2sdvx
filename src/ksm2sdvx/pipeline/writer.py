"""Stage a complete LayeredFS mod directory and publish it once."""

import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from ksm2sdvx.chart import serialize_vox
from ksm2sdvx.common.errors import OutputError
from ksm2sdvx.common.types import JsonValue, json_ready
from ksm2sdvx.metadata import SdvxMetadata, serialize_music_database
from ksm2sdvx.pipeline.models import PackageWriteResult, SdvxPackage


def _relative_path(name: str | PurePosixPath) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or "\\" in str(name):
        raise OutputError("Package output paths must be relative POSIX paths")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    for part in path.parts:
        if (
            part in {".", ".."}
            or part.endswith((" ", "."))
            or any(c in part for c in ':<>"|?*\x00')
            or part.split(".")[0].casefold() in reserved
        ):
            raise OutputError(f"Invalid package output path: {name}")
    return path


class LayeredFsPackageWriter:
    def __init__(self, *, report: Mapping[str, JsonValue] | None = None) -> None:
        self.report = report

    def write(
        self,
        package: SdvxPackage[SdvxMetadata],
        *,
        destination: Path,
    ) -> PackageWriteResult:
        """Create a new mod folder; existing output is never replaced or merged."""
        names = (
            *(_relative_path(chart.output_name) for chart in package.charts),
            *(_relative_path(resource.output_path) for resource in package.resources),
            PurePosixPath("others/music_db.merged.xml"),
            PurePosixPath("ksm2sdvx-report.json"),
        )
        seen: set[str] = set()
        for path in names:
            key = str(path).casefold()
            if key in seen:
                raise OutputError(f"Conflicting package output: {path}")
            seen.add(key)
        for path in names:
            if any(str(parent).casefold() in seen for parent in path.parents if str(parent) != "."):
                raise OutputError(f"Package file conflicts with a directory: {path}")
        try:
            if destination.exists() or destination.is_symlink():
                raise OutputError("Package output already exists; choose a new destination")
            destination = destination.absolute()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".ksm2sdvx-package-", dir=destination.parent
            ) as temp:
                stage = Path(temp) / "mod"
                stage.mkdir()
                for chart in package.charts:
                    output = stage / _relative_path(chart.output_name)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(serialize_vox(chart.chart), encoding="utf-8", newline="\n")
                for resource in package.resources:
                    source = resource.resource.path
                    if not source.is_file():
                        raise OutputError(f"Processed resource is missing: {resource.output_path}")
                    output = stage / _relative_path(resource.output_path)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, output)
                metadata = stage / "others/music_db.merged.xml"
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_bytes(serialize_music_database(package.metadata))
                report: dict[str, JsonValue] = dict(self.report or {})
                report["schema_version"] = 1
                report["files"] = tuple(str(path) for path in names)
                (stage / "ksm2sdvx-report.json").write_text(
                    json.dumps(json_ready(report), ensure_ascii=False, allow_nan=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                if destination.exists() or destination.is_symlink():
                    raise OutputError("Package output was created during conversion")
                stage.rename(destination)
            return PackageWriteResult(
                destination,
                tuple(destination / path for path in names),
                package.diagnostics,
            )
        except OSError as exc:
            raise OutputError(f"Cannot write package: {exc}") from exc
