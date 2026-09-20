"""Load explicit charts and inspect resources without output mutations."""

from dataclasses import replace

from ksm2sdvx.chart import ConversionOptions, VoxProfile, convert_chart, load_kson
from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.pipeline.models import InspectedChart, PackageInspection, SourcePackage
from ksm2sdvx.resources.discovery import discover_resources
from ksm2sdvx.resources.errors import AssetError
from ksm2sdvx.resources.models import ResourceInput


def inspect_package(
    source: SourcePackage,
    *,
    options: ConversionOptions,
    profile: VoxProfile,
) -> PackageInspection:
    options.validate()
    profile.validate()
    try:
        root = source.root.resolve()
        if not root.is_dir() or not source.charts:
            raise AssetError("Package inspection requires an existing root and at least one chart")
    except (OSError, ValueError) as exc:
        raise AssetError(f"Cannot resolve source root: {exc}") from exc
    charts: list[InspectedChart] = []
    references: list[ResourceInput] = []
    outputs: set[str] = set()
    diagnostics: list[Diagnostic] = []
    for raw_path in source.charts:
        try:
            path = raw_path.resolve()
        except (OSError, ValueError) as exc:
            raise AssetError(f"Cannot resolve source chart: {exc}") from exc
        if not path.is_relative_to(root):
            raise AssetError(f"Chart escapes package root: {path}")
        output_name = path.stem + ".vox"
        if output_name.casefold() in outputs:
            raise AssetError(f"Conflicting chart output filename: {output_name}")
        outputs.add(output_name.casefold())
        parsed = load_kson(path)
        result = convert_chart(parsed.chart, options=options, profile=profile)
        charts.append(InspectedChart(path, output_name, parsed.chart, result, parsed.diagnostics))
        diagnostics.extend(parsed.diagnostics)
        diagnostics.extend(replace(d, source_path=str(path)) for d in result.report.diagnostics)
        references.extend(ResourceInput(path, reference) for reference in parsed.chart.assets)
    inventory = discover_resources(references, root=root)
    diagnostics.extend(inventory.diagnostics)
    return PackageInspection(root, tuple(charts), inventory.assets, tuple(diagnostics))
