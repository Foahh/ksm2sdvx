"""Contained resource resolution and deduplication without opening asset contents."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.resources.errors import AssetError
from ksm2sdvx.resources.models import (
    ResourceInput,
    ResourceInventory,
    ResourceRecord,
    ResourceReference,
    ResourceUse,
)


def resolve_resource(reference: ResourceReference, owner: Path, root: Path) -> Path | None:
    if reference.preset:
        return None
    # Interpret source-relative paths consistently on Windows and POSIX.
    name = reference.name.replace("\\", "/")
    windows = PureWindowsPath(name)
    if windows.drive or windows.root or Path(name).is_absolute() or ":" in name or "\x00" in name:
        raise AssetError(f"{reference.path}: asset paths must be relative to the source file")
    try:
        resolved = (owner.parent / name).resolve()
    except (OSError, ValueError) as exc:
        raise AssetError(f"{reference.path}: cannot resolve asset: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise AssetError(f"{reference.path}: asset escapes the package root")
    return resolved


def discover_resources(inputs: Iterable[ResourceInput], *, root: Path) -> ResourceInventory:
    """Inventory references relative to their owners, within an existing source root."""
    try:
        root = root.resolve()
        if not root.is_dir():
            raise AssetError("Resource discovery requires an existing root")
    except (OSError, ValueError) as exc:
        raise AssetError(f"Cannot resolve resource root: {exc}") from exc
    assets: dict[tuple[str, ...], ResourceRecord] = {}
    diagnostics: list[Diagnostic] = []
    for item in inputs:
        reference = item.reference
        try:
            owner = item.owner.resolve()
            if not owner.is_relative_to(root):
                raise AssetError(f"Source escapes the package root: {owner}")
            resolved = resolve_resource(reference, owner, root)
            exists = resolved is None or resolved.is_file()
        except (AssetError, OSError, ValueError) as exc:
            diagnostics.append(
                Diagnostic(
                    "INVALID_ASSET_PATH",
                    Severity.ERROR,
                    Stage.INSPECT,
                    str(exc),
                    reference.role,
                    reference.path,
                    source_path=str(item.owner),
                )
            )
            continue
        if not exists:
            diagnostics.append(
                Diagnostic(
                    "MISSING_ASSET",
                    Severity.ERROR,
                    Stage.INSPECT,
                    f"Missing asset: {reference.name}",
                    reference.role,
                    reference.path,
                    source_path=str(owner),
                )
            )
        use = ResourceUse(owner, reference.role, reference.path)
        key = (
            ("file", str(resolved))
            if resolved is not None
            else ("preset", reference.role, reference.name)
        )
        if key in assets:
            assets[key] = replace(assets[key], uses=(*assets[key].uses, use))
        else:
            assets[key] = ResourceRecord(reference.name, resolved, reference.preset, exists, (use,))
    return ResourceInventory(tuple(assets.values()), tuple(diagnostics))
