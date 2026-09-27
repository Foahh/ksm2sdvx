"""Translate a validated draft and filesystem snapshot into explicit file changes."""

from collections import Counter
from dataclasses import replace
from pathlib import Path

from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.database import edit_database, parse_database
from ksm2sdvx.packs.discovery import (
    conflicting_asset,
    discover_assets,
    external_jacket_references,
    pack_root,
    tree_revision,
)
from ksm2sdvx.packs.draft import validate_draft
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, ChangePlan, FileChange, PackDraft, Workspace
from ksm2sdvx.packs.paths import contained, digest, fingerprint


def plan_changes(workspace: Workspace, draft: PackDraft) -> ChangePlan:
    validate_draft(workspace, draft)
    assert draft.pack.database is not None
    root = pack_root(workspace, draft.pack)
    external_jackets = external_jacket_references(workspace, draft.pack.name)
    shared_jackets = external_jackets | {
        int(value)
        for song in draft.pack.database.songs
        for path, value in song.fields
        if path.endswith("/jacket_print") and value.isdecimal() and int(value) > 0
    }
    if draft.create and root.exists():
        raise PackError("The new song pack destination already exists")
    if draft.remove_pack:
        if draft.create:
            raise PackError("Discard a new pack instead of removing it")
        if external_jackets & {song.song_id for song in draft.pack.database.songs}:
            raise PackError(
                "Unresolved jacket metadata in another library affects this pack; removal is blocked"
            )
        return ChangePlan(
            workspace,
            draft.pack.name,
            (),
            remove_pack=True,
            tree=tree_revision(root),
            summary=(f"Remove song pack {draft.pack.name}",),
        )
    output: dict[str, bytes | Path | None] = {}
    summary = [f"Create song pack {draft.pack.name}"] if draft.create else []
    data = edit_database(
        draft.pack.database,
        draft.edits,
        draft.removed,
        tuple(item.database for item in draft.additions),
    )
    resulting = replace(draft.pack, database=parse_database(data))
    # Newly enabled slots require understood loose inputs. Existing unavailable
    # or archived assets do not prevent an unrelated metadata edit.
    enabled = {
        edit.song_index
        for edit in draft.edits
        if edit.path.endswith("/difnum")
        and int(edit.value) > 0
        and draft.pack.database.songs[edit.song_index].value(edit.path, "0") in {"", "0"}
    }
    supplied = {r.relative for r in draft.replacements}
    supplied.update(r.relative for addition in draft.additions for r in addition.assets)
    original_ids = {draft.pack.database.songs[i].song_id for i in enabled}
    required_indices = (
        {song.index for song in resulting.database.songs if song.song_id in original_ids}
        if resulting.database
        else set[int]()
    )
    for asset in discover_assets(workspace, resulting):
        if (
            set(asset.owners) & required_indices
            and asset.kind in {"Chart", "Gameplay audio", "Preview audio"}
            and not asset.exists
            and asset.relative not in supplied
        ):
            raise PackError(f"Enabled chart requires a loose asset: {asset.relative}")
    if data != draft.pack.database.content or draft.create:
        output[DATABASE] = data
    for edit in draft.edits:
        song = draft.pack.database.songs[edit.song_index]
        summary.append(f"{song.title}: {edit.path} → {edit.value}")
    replacements = list(draft.replacements)
    known_assets = {a.relative: a for a in discover_assets(workspace, draft.pack)}
    counts = Counter(
        song.song_id for pack in workspace.packs if pack.database for song in pack.database.songs
    )
    for replacement in replacements:
        asset = known_assets.get(replacement.relative)
        if asset is None or asset.kind not in {
            "Gameplay audio",
            "Preview audio",
            "Jacket",
            "Selector jacket",
        }:
            raise PackError("Replacement is not an understood audio or jacket asset")
        if any(counts[draft.pack.database.songs[index].song_id] > 1 for index in asset.owners):
            raise PackError("The replacement affects a conflicting song ID")
    for addition in draft.additions:
        parsed = parse_database(addition.database)
        if len(parsed.songs) != 1:
            raise PackError("A prepared import must contain one song")
        song = parsed.songs[0]
        asset_names = {r.relative for r in addition.assets}
        playable = [
            slot
            for slot in ChartSlot
            if song.value(f"difficulty/{slot.value}/difnum", "0") not in {"", "0"}
        ]
        if not playable:
            raise PackError("A prepared song needs a playable chart")
        for slot in playable:
            stem = f"music/{song.stem}/{song.stem}"
            if f"{stem}_{slot.suffix}.vox" not in asset_names or not any(
                name in asset_names
                for name in (
                    f"{stem}_{slot.suffix}.s3v",
                    f"{stem}.s3v",
                    f"{stem}_{slot.suffix}.2dx",
                    f"{stem}.2dx",
                )
            ):
                raise PackError("A prepared song is missing charts or gameplay audio")
        if not any(
            f"music/{song.stem}/{song.stem}_pre{suffix}" in asset_names
            for suffix in (".s3v", ".2dx")
        ):
            raise PackError("A prepared song is missing preview audio")
        replacements.extend(addition.assets)
        summary.append("Add prepared song and its assets")
    seen: set[str] = set()
    for asset in replacements:
        key = asset.relative.casefold()
        if key in seen or key == DATABASE.casefold():
            raise PackError(f"Conflicting prepared asset: {asset.relative}")
        seen.add(key)
        destination = contained(root, asset.relative)
        if fingerprint(asset.source) != asset.digest:
            raise PackError("A prepared asset changed; prepare it again")
        # Imports cannot overwrite another song's assets.
        if asset not in draft.replacements and destination.exists():
            raise PackError(f"Imported asset already exists: {asset.relative}")
        if conflicting_asset(workspace.root, draft.pack.name, asset.relative):
            raise PackError(f"Asset has a conflicting overlay: {asset.relative}")
        if asset.relative.endswith(".png") and any(
            f"/jk_{song_id:04}_" in asset.relative for song_id in shared_jackets
        ):
            raise PackError("Unresolved jacket metadata affects this asset; replacement is blocked")
        output[asset.relative] = asset.source
        summary.append(f"Write {asset.relative}")
    removed = set(draft.removed)
    for asset in known_assets.values():
        if asset.exists and asset.owners and set(asset.owners) <= removed:
            if asset.kind in {"Jacket", "Selector jacket"} and any(
                f"/jk_{song_id:04}_" in asset.relative for song_id in shared_jackets
            ):
                continue
            if asset.relative in output:
                raise PackError("Cannot replace an asset belonging to a removed song")
            output[asset.relative] = None
    for index in draft.removed:
        summary.append(f"Remove {draft.pack.database.songs[index].title}")
    changes: list[FileChange] = []
    for relative, content in output.items():
        before = fingerprint(contained(root, relative))
        after = (
            digest(content)
            if isinstance(content, bytes)
            else (fingerprint(content) if isinstance(content, Path) else None)
        )
        if before != after:
            changes.append(FileChange(relative, before, after, content))
    changes.sort(
        key=lambda c: (
            2 if c.after is None else 1 if c.relative == DATABASE else 0,
            c.relative.casefold(),
        )
    )
    return ChangePlan(
        workspace, draft.pack.name, tuple(changes), draft.create, summary=tuple(summary)
    )
