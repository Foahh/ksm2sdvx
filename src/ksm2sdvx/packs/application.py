"""Application boundaries for preparation, inspection and portable exports."""

import json
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from ksm2sdvx.chart import ConversionOptions, VoxProfile
from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.jobs import JobControl, checkpoint
from ksm2sdvx.jacket.application import convert_jacket_file
from ksm2sdvx.jacket.models import JacketSettings, JacketSize
from ksm2sdvx.music.application import convert_audio_file
from ksm2sdvx.music.models import S3vMusicSettings
from ksm2sdvx.packs.database import parse_database, validate_new_song
from ksm2sdvx.packs.discovery import (
    discover_assets,
    inspect_game,
    pack_root,
    problem,
    tree_revision,
)
from ksm2sdvx.packs.draft import validate_draft, writable
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import (
    DATABASE,
    Asset,
    Pack,
    PackDraft,
    PreparedSong,
    Replacement,
    Workspace,
)
from ksm2sdvx.packs.paths import contained, fingerprint
from ksm2sdvx.packs.storage import recover_pending
from ksm2sdvx.pipeline.build import build_package
from ksm2sdvx.pipeline.config import PackageConfig


@dataclass(frozen=True, slots=True)
class OpenedPack:
    pack: Pack
    assets: tuple[Asset, ...]


@dataclass(frozen=True, slots=True)
class ToolPaths:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


def prepared_assets(song: PreparedSong, index: int) -> tuple[Asset, ...]:
    result: list[Asset] = []
    for asset in song.assets:
        name = asset.relative
        kind = (
            "Chart"
            if name.endswith(".vox")
            else "Sampler"
            if name.endswith(".s3p")
            else "Selector jacket"
            if name.endswith("_t.png")
            else "Jacket"
            if name.endswith(".png")
            else "Preview audio"
            if "_pre." in name
            else "Gameplay audio"
        )
        result.append(Asset(name, kind, True, (index,)))
    return tuple(result)


def open_workspace(root: Path, control: JobControl | None = None) -> Workspace:
    # Validate before allowing recovery to touch this directory.
    inspect_game(root, control=control)
    checkpoint(control, "Reconciling interrupted applies")
    try:
        recover_pending(root)
    except (OSError, PackError) as exc:
        snapshot = inspect_game(root, control=control)
        diagnostic = problem("RECOVERY_REQUIRED", str(exc))
        return replace(
            snapshot,
            complete=False,
            recovery_error=str(exc),
            packs=tuple(
                replace(p, readonly=True, diagnostics=(*p.diagnostics, diagnostic))
                for p in snapshot.packs
            ),
        )
    return inspect_game(root, control=control)


def open_pack(workspace: Workspace, pack: Pack, control: JobControl | None = None) -> OpenedPack:
    checkpoint(control, "Inspecting loose assets")
    assets = discover_assets(workspace, pack)
    checkpoint(control, "Pack ready")
    return OpenedPack(pack, assets)


def add_prepared(workspace: Workspace, draft: PackDraft, prepared: PreparedSong) -> PackDraft:
    writable(draft)
    result = replace(draft, additions=(*draft.additions, prepared))
    validate_draft(workspace, result)
    return result


def remove_song(draft: PackDraft, index: int) -> PackDraft:
    writable(draft)
    assert draft.pack.database is not None
    count = len(draft.pack.database.songs)
    if index >= count:
        position = index - count
        if not 0 <= position < len(draft.additions):
            raise PackError("Song selection is stale")
        return replace(
            draft, additions=draft.additions[:position] + draft.additions[position + 1 :]
        )
    if not 0 <= index < count:
        raise PackError("Song selection is stale")
    if index in draft.removed:
        return replace(draft, removed=tuple(i for i in draft.removed if i != index))
    return replace(
        draft,
        removed=(*draft.removed, index),
        edits=tuple(e for e in draft.edits if e.song_index != index),
    )


def _replacement(relative: str, source: Path) -> Replacement:
    value = fingerprint(source)
    if value is None:
        raise PackError(f"Required prepared file is missing: {relative}")
    return Replacement(relative, source, value)


def prepare_generated(
    source: Path,
    area: Path,
    *,
    control: JobControl | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> PreparedSong:
    """Import a generated single-song package without changing its identities."""
    source = source.resolve()
    report = contained(source, "ksm2sdvx-report.json")
    try:
        raw: object = json.loads(report.read_bytes())
    except (OSError, ValueError) as exc:
        raise PackError("Select a generated song pack containing ksm2sdvx-report.json") from exc
    if not isinstance(raw, dict) or cast(dict[str, object], raw).get("schema_version") != 1:
        raise PackError("Unsupported generated song pack report")
    database = parse_database(contained(source, DATABASE).read_bytes())
    if len(database.songs) != 1:
        raise PackError("Generated import requires exactly one song")
    validate_new_song(database.songs[0])
    # The source is inspected as a pack; only understood song assets are imported.
    synthetic = Workspace(source.parent.parent, (), (), True)
    pack = Pack(source.name, database)
    # Asset discovery supports standalone packages through an explicit root override.
    assets = discover_assets(synthetic, pack, root=source)
    if not any(a.kind == "Chart" for a in assets):
        raise PackError("The generated song has no playable chart")
    required = [a for a in assets if a.kind in {"Chart", "Gameplay audio", "Preview audio"}]
    if any(not a.exists for a in required):
        raise PackError("The generated song is missing required loose charts or audio")
    destination = area / uuid.uuid4().hex
    destination.mkdir(parents=True)
    outputs: list[Replacement] = []
    for asset in assets:
        if not asset.exists:
            continue
        checkpoint(control, f"Preparing {asset.relative}")
        original = contained(source, asset.relative)
        before = fingerprint(original)
        target = contained(destination, asset.relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        prepared = _replacement(asset.relative, target)
        if prepared.digest != before or fingerprint(original) != before:
            raise PackError("Import source changed during preparation")
        outputs.append(prepared)
    checkpoint(control, "Prepared song ready for review")
    return PreparedSong(database.content, tuple(outputs), diagnostics)


def prepare_kson(
    config: PackageConfig,
    area: Path,
    tools: ToolPaths | None = None,
    control: JobControl | None = None,
) -> PreparedSong:
    tools = tools if tools is not None else ToolPaths()
    destination = area / uuid.uuid4().hex
    result = build_package(
        config,
        destination=destination,
        options=ConversionOptions(),
        profile=VoxProfile(),
        ffmpeg=tools.ffmpeg,
        ffprobe=tools.ffprobe,
        control=control,
    )
    return prepare_generated(destination, area, control=control, diagnostics=result.diagnostics)


def prepare_asset(
    asset: Asset,
    source: Path,
    area: Path,
    *,
    tools: ToolPaths | None = None,
    audio: S3vMusicSettings | None = None,
    control: JobControl | None = None,
) -> Replacement:
    tools = tools if tools is not None else ToolPaths()
    audio = audio if audio is not None else S3vMusicSettings()
    checkpoint(control, "Converting replacement; the current media operation must finish")
    destination = area / uuid.uuid4().hex / Path(asset.relative).name
    destination.parent.mkdir(parents=True)
    if asset.kind in {"Jacket", "Selector jacket"}:
        size = (
            JacketSize.SELECTOR
            if asset.relative.endswith("_t.png")
            else JacketSize.SMALL
            if asset.relative.endswith("_s.png")
            else JacketSize.LARGE
            if asset.relative.endswith("_b.png")
            else JacketSize.STANDARD
        )
        convert_jacket_file(
            source,
            output=destination,
            settings=JacketSettings(size),
            ffmpeg=tools.ffmpeg,
            ffprobe=tools.ffprobe,
        )
    elif asset.kind in {"Gameplay audio", "Preview audio"} and asset.relative.endswith(".s3v"):
        if asset.kind == "Preview audio" and audio.preview_duration_ms is None:
            raise PackError("Preview replacement requires an explicit interval")
        convert_audio_file(source, output=destination, settings=audio, ffmpeg=tools.ffmpeg)
    else:
        raise PackError("Only loose S3V audio and PNG jackets can be replaced")
    checkpoint(control, "Replacement ready for review")
    return _replacement(asset.relative, destination)


def export_pack(
    workspace: Workspace, pack: Pack, destination: Path, control: JobControl | None = None
) -> Path:
    if pack.readonly or pack.database is None:
        raise PackError("Only supported song packs can be exported")
    root = pack_root(workspace, pack)
    destination = destination.absolute()
    if destination.exists() or destination.resolve().is_relative_to(workspace.root):
        raise PackError("Choose a new export directory outside the game folder")
    before = tree_revision(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}")
    stage.mkdir()
    try:
        for entry in before:
            checkpoint(control, f"Exporting {entry.path}")
            target = contained(stage, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(contained(root, entry.path), target)
            if fingerprint(target) != entry.digest:
                raise PackError("Song pack changed during export")
        if tree_revision(root) != before:
            raise PackError("Song pack changed during export")
        checkpoint(control, "Publishing export")
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(contained(destination.parent, stage.name))
    return destination
