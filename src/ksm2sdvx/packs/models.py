"""Immutable snapshots and explicit edits for installed song packs."""

from dataclasses import dataclass
from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic

DATABASE = "others/music_db.merged.xml"
ORIGINAL = "@original"


@dataclass(frozen=True, slots=True)
class Song:
    index: int
    song_id: int
    fields: tuple[tuple[str, str], ...]
    readonly_fields: tuple[str, ...] = ()

    def value(self, path: str, default: str = "") -> str:
        return next((value for name, value in self.fields if name == path), default)

    @property
    def title(self) -> str:
        return self.value("info/title_name", f"Song {self.song_id}")

    @property
    def artist(self) -> str:
        return self.value("info/artist_name")

    @property
    def stem(self) -> str:
        return f"{self.song_id:04}_{self.value('info/ascii')}"


@dataclass(frozen=True, slots=True)
class Database:
    content: bytes
    encoding: str
    declaration: str
    songs: tuple[Song, ...]


@dataclass(frozen=True, slots=True)
class Revision:
    path: str
    digest: str


@dataclass(frozen=True, slots=True)
class Pack:
    name: str
    database: Database | None
    readonly: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    packs: tuple[Pack, ...]
    revisions: tuple[Revision, ...]
    complete: bool
    recovery_error: str = ""
    mod_directories: tuple[str, ...] = ()

    def pack(self, name: str) -> Pack:
        return next(pack for pack in self.packs if pack.name == name)


@dataclass(frozen=True, slots=True)
class FieldEdit:
    song_index: int
    path: str
    value: str


@dataclass(frozen=True, slots=True)
class Replacement:
    relative: str
    source: Path
    digest: str


@dataclass(frozen=True, slots=True)
class PreparedSong:
    database: bytes
    assets: tuple[Replacement, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class PackDraft:
    pack: Pack
    create: bool = False
    remove_pack: bool = False
    edits: tuple[FieldEdit, ...] = ()
    additions: tuple[PreparedSong, ...] = ()
    removed: tuple[int, ...] = ()
    replacements: tuple[Replacement, ...] = ()

    @property
    def dirty(self) -> bool:
        return bool(
            self.create
            or self.remove_pack
            or self.edits
            or self.additions
            or self.removed
            or self.replacements
        )


@dataclass(frozen=True, slots=True)
class FileChange:
    relative: str
    before: str | None
    after: str | None
    content: bytes | Path | None


@dataclass(frozen=True, slots=True)
class ChangePlan:
    workspace: Workspace
    pack_name: str
    changes: tuple[FileChange, ...]
    create: bool = False
    remove_pack: bool = False
    tree: tuple[Revision, ...] = ()
    summary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Asset:
    relative: str
    kind: str
    exists: bool
    owners: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Recovery:
    transaction: str
    pack_name: str
    status: str
    description: str
