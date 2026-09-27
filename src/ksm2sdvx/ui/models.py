"""Song identities stay stable when proxy sorting and filtering change rows."""

from collections import Counter
from dataclasses import dataclass, replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.database import parse_database
from ksm2sdvx.packs.models import PackDraft, Song, Workspace

ROOT_INDEX = QModelIndex()


@dataclass(frozen=True, slots=True)
class SongRow:
    song: Song
    status: str


def song_rows(
    workspace: Workspace, draft: PackDraft, changed_assets: frozenset[int] = frozenset()
) -> tuple[SongRow, ...]:
    counts = Counter(s.song_id for p in workspace.packs if p.database for s in p.database.songs)
    songs = draft.pack.database.songs if draft.pack.database else ()
    rows: list[SongRow] = []
    for song in songs:
        edits = {e.path: e.value for e in draft.edits if e.song_index == song.index}
        values = (
            tuple((path, edits.get(path, value)) for path, value in song.fields)
            if edits
            else song.fields
        )
        status = (
            "Conflict"
            if counts[song.song_id] > 1
            else "Remove"
            if song.index in draft.removed or draft.remove_pack
            else "Changed"
            if edits or song.index in changed_assets
            else "Read-only"
            if draft.pack.readonly
            else "Ready"
        )
        rows.append(SongRow(replace(song, fields=values) if edits else song, status))
    for index, addition in enumerate(draft.additions, len(songs)):
        song = parse_database(addition.database).songs[0]
        rows.append(SongRow(replace(song, index=index), "New"))
    return tuple(rows)


class SongTableModel(QAbstractTableModel):
    HEADERS = ("ID", "Title", "Artist", "BPM", "Charts", "Status")

    def __init__(self) -> None:
        super().__init__()
        self.rows: tuple[SongRow, ...] = ()

    def set_rows(self, rows: tuple[SongRow, ...]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        song = row.song
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{song.stem}\n{row.status}"
        if role not in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole}:
            return None
        minimum, maximum = song.value("info/bpm_min"), song.value("info/bpm_max")
        try:
            low, high = int(minimum) / 100, int(maximum) / 100
            bpm = f"{low:g}" if low == high else f"{low:g}–{high:g}"
        except ValueError:
            low = 0.0
            bpm = f"{minimum} / {maximum}"
        if index.column() == 3 and role == Qt.ItemDataRole.UserRole:
            return low
        if index.column() == 0 and role == Qt.ItemDataRole.DisplayRole:
            return f"{song.song_id:04}"
        charts = " / ".join(
            slot.value[:3].upper()
            for slot in ChartSlot
            if song.value(f"difficulty/{slot.value}/difnum", "0") not in {"", "0"}
        )
        return (song.song_id, song.title, song.artist, bpm, charts, row.status)[index.column()]
