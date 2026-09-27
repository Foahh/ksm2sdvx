"""Pure draft changes and identity validation."""

from dataclasses import replace

from ksm2sdvx.metadata.models import MAX_SONG_ID
from ksm2sdvx.packs.database import (
    edit_database,
    empty_database,
    parse_database,
    validate_new_song,
    validate_value,
)
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import ORIGINAL, FieldEdit, Pack, PackDraft, Workspace
from ksm2sdvx.packs.paths import pack_name


def writable(draft: PackDraft) -> None:
    if draft.pack.readonly or draft.pack.name == ORIGINAL or draft.pack.database is None:
        raise PackError("This song database is read-only")
    pack_name(draft.pack.name)


def create_draft(workspace: Workspace, name: str) -> PackDraft:
    if workspace.recovery_error:
        raise PackError("Resolve unfinished recovery before creating a pack")
    pack_name(name)
    if any(pack.name.casefold() == name.casefold() for pack in workspace.packs):
        raise PackError("A song pack with this name already exists")
    return PackDraft(Pack(name, empty_database()), create=True)


def set_field(draft: PackDraft, index: int, path: str, value: str) -> PackDraft:
    writable(draft)
    validate_value(path, value)
    assert draft.pack.database is not None
    count = len(draft.pack.database.songs)
    if count <= index < count + len(draft.additions):
        position = index - count
        addition = draft.additions[position]
        content = edit_database(parse_database(addition.database), (FieldEdit(0, path, value),))
        return replace(
            draft,
            additions=(
                *draft.additions[:position],
                replace(addition, database=content),
                *draft.additions[position + 1 :],
            ),
        )
    if index < 0 or index >= len(draft.pack.database.songs) or index in draft.removed:
        raise PackError("Select an existing song to edit")
    song = draft.pack.database.songs[index]
    if path in song.readonly_fields or sum(name == path for name, _ in song.fields) != 1:
        raise PackError("Missing or ambiguous fields are read-only")
    if path.endswith("/jacket_print"):
        raise PackError("Existing jacket identities are read-only")
    try:
        value.encode(draft.pack.database.encoding)
    except UnicodeError as exc:
        raise PackError("Edited text cannot be represented in the database encoding") from exc
    original = draft.pack.database.songs[index].value(path)
    edits = tuple(edit for edit in draft.edits if (edit.song_index, edit.path) != (index, path))
    if original != value:
        edits += (FieldEdit(index, path, value),)
    # Full-document serialization belongs to background review planning.
    return replace(draft, edits=edits)


def projected(draft: PackDraft) -> Pack:
    if draft.pack.database is None:
        return draft.pack
    content = edit_database(
        draft.pack.database,
        draft.edits,
        draft.removed,
        tuple(item.database for item in draft.additions),
    )
    return replace(draft.pack, database=parse_database(content))


def next_song_id(workspace: Workspace, draft: PackDraft) -> int:
    if not workspace.complete:
        raise PackError(
            "The installation ID inventory is incomplete; resolve database problems first"
        )
    used = {
        song.song_id for pack in workspace.packs if pack.database for song in pack.database.songs
    }
    used.update(
        song.song_id for item in draft.additions for song in parse_database(item.database).songs
    )
    for candidate in range(1, MAX_SONG_ID + 1):
        if candidate not in used:
            return candidate
    raise PackError("No unused song ID remains in the supported range")


def validate_draft(workspace: Workspace, draft: PackDraft) -> None:
    if workspace.recovery_error:
        raise PackError("Resolve unfinished recovery before applying changes")
    writable(draft)
    assert draft.pack.database is not None
    owners: dict[int, list[str]] = {}
    for pack in workspace.packs:
        if pack.database:
            for song in pack.database.songs:
                owners.setdefault(song.song_id, []).append(pack.name)
    touched = {edit.song_index for edit in draft.edits} | set(draft.removed)
    if draft.remove_pack:
        touched.update(song.index for song in draft.pack.database.songs)
    for index in touched:
        if index < 0 or index >= len(draft.pack.database.songs):
            raise PackError("Song selection is stale")
        song = draft.pack.database.songs[index]
        if len(owners.get(song.song_id, [])) > 1:
            raise PackError(
                f"Song ID {song.song_id} has conflicting entries; this change is blocked"
            )
    if draft.additions and not workspace.complete:
        raise PackError("The installation ID inventory is incomplete")
    for addition in draft.additions:
        for song in parse_database(addition.database).songs:
            validate_new_song(song)
            if not 1 <= song.song_id <= MAX_SONG_ID or song.song_id in owners:
                raise PackError(f"Song ID {song.song_id} is unavailable")
            owners[song.song_id] = [draft.pack.name]
    projected(draft)
    for edit in draft.edits:
        if edit.path.endswith(("/bpm_min", "/bpm_max")):
            song = draft.pack.database.songs[edit.song_index]
            values = dict(song.fields)
            values.update((e.path, e.value) for e in draft.edits if e.song_index == edit.song_index)
            try:
                if int(values["info/bpm_min"]) > int(values["info/bpm_max"]):
                    raise PackError("Minimum BPM must not exceed maximum BPM")
            except (ValueError, KeyError) as exc:
                raise PackError("BPM range is ambiguous") from exc
