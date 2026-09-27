"""Preservation-aware XML editing using a private DOM and immutable snapshots."""

import codecs
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import Database, FieldEdit, Song


@dataclass(frozen=True, slots=True)
class FieldSpec:
    path: str
    label: str
    minimum: int | None = None
    maximum: int | None = None
    advanced: bool = False


SONG_FIELDS = (
    FieldSpec("info/title_name", "Title"),
    FieldSpec("info/artist_name", "Artist"),
    FieldSpec("info/title_yomigana", "Title reading"),
    FieldSpec("info/artist_yomigana", "Artist reading"),
    FieldSpec("info/bpm_min", "Minimum BPM × 100", 0, 2**32 - 1),
    FieldSpec("info/bpm_max", "Maximum BPM × 100", 0, 2**32 - 1),
    FieldSpec("info/volume", "Volume", 0, 65535),
    FieldSpec("info/distribution_date", "Distribution date (YYYYMMDD)", advanced=True),
    FieldSpec("info/version", "Version", 1, 255, True),
    FieldSpec("info/bg_no", "Background", 0, 65535, True),
    FieldSpec("info/genre", "Genre", 0, 2**32 - 1, True),
    FieldSpec("info/is_fixed", "Fixed", 0, 255, True),
    FieldSpec("info/demo_pri", "Demo priority", -128, 127, True),
    FieldSpec("info/inf_ver", "Infinite version", 0, 255, True),
    FieldSpec("info/license_text", "License", advanced=True),
)
CHART_FIELDS = (
    FieldSpec("difnum", "Level (stored value)", 0, 255),
    FieldSpec("effected_by", "Chart author"),
    FieldSpec("illustrator", "Jacket author"),
    FieldSpec("price", "Price", -(2**31), 2**31 - 1, True),
    FieldSpec("limited", "Limited", 0, 255, True),
    FieldSpec("jacket_print", "Jacket print (stored value)", -(2**31), 2**31 - 1, True),
    FieldSpec("jacket_mask", "Jacket mask", -(2**31), 2**31 - 1, True),
    FieldSpec("max_exscore", "Maximum EX score", 0, 2**31 - 1, True),
    *(
        FieldSpec(f"radar/{name}", f"Radar {name}", 0, 65535, True)
        for name in ("notes", "peak", "tsumami", "tricky", "hand-trip", "one-hand")
    ),
)


def field_spec(path: str) -> FieldSpec:
    for field in SONG_FIELDS:
        if field.path == path:
            return field
    parts = path.split("/", 2)
    if len(parts) == 3 and parts[0] == "difficulty" and parts[1] in ChartSlot:
        for field in CHART_FIELDS:
            if field.path == parts[2]:
                return field
    raise PackError(f"Field is not editable: {path}")


def validate_value(path: str, value: str) -> None:
    spec = field_spec(path)
    if any(
        not (
            ord(c) in {9, 10, 13}
            or 0x20 <= ord(c) <= 0xD7FF
            or 0xE000 <= ord(c) <= 0xFFFD
            or 0x10000 <= ord(c) <= 0x10FFFF
        )
        for c in value
    ):
        raise PackError("Text contains a character that XML cannot represent")
    if path in {"info/title_name", "info/artist_name"} and not value.strip():
        raise PackError(f"{spec.label} cannot be empty")
    if spec.minimum is not None:
        try:
            number = int(value)
        except ValueError as exc:
            raise PackError(f"{spec.label} must be an integer") from exc
        if number < spec.minimum or (spec.maximum is not None and number > spec.maximum):
            raise PackError(f"{spec.label} must be between {spec.minimum} and {spec.maximum}")
    if path == "info/distribution_date":
        try:
            if len(value) != 8:
                raise ValueError
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise PackError("Distribution date must be a valid YYYYMMDD date") from exc


def _children(node: minidom.Node, name: str) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if isinstance(child, minidom.Element) and child.tagName == name
    ]


def _element(node: minidom.Node, path: str) -> minidom.Element | None:
    current = node
    for part in path.split("/"):
        matches = _children(current, part)
        if len(matches) != 1:
            return None
        current = matches[0]
    return current if isinstance(current, minidom.Element) else None


def _parse(text: str) -> minidom.Document:
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise PackError("DTD and entity declarations are unsupported")
    try:
        document = minidom.parseString(text)
    except (ExpatError, ValueError) as exc:
        raise PackError(f"Cannot parse song database: {exc}") from exc
    if document.documentElement is None or document.documentElement.tagName != "mdb":
        raise PackError("Expected an mdb database root")
    return document


def parse_database(content: bytes) -> Database:
    declaration_match = re.match(rb"(?:\xef\xbb\xbf)?\s*(<\?xml[^?]*\?>)", content)
    declaration = declaration_match[1].decode("ascii") if declaration_match else ""
    match = re.search(r"encoding\s*=\s*['\"]([^'\"]+)", declaration, re.IGNORECASE)
    name = match[1].lower().replace("-", "_") if match else "utf_8"
    if name in {"shift_jis", "sjis", "windows_31j", "cp932"}:
        encoding = "cp932"
    elif name in {"utf_8", "utf8"}:
        encoding = "utf-8-sig" if content.startswith(codecs.BOM_UTF8) else "utf-8"
    else:
        raise PackError(f"Unsupported song database encoding: {name}")
    try:
        text = content.decode(encoding)
    except UnicodeError as exc:
        raise PackError("Song database is not supported text XML") from exc
    doc = _parse(text)
    assert doc.documentElement is not None
    songs: list[Song] = []
    try:
        for index, entry in enumerate(_children(doc.documentElement, "music")):
            try:
                song_id = int(entry.getAttribute("id"))
            except ValueError as exc:
                raise PackError("A song entry has an invalid ID") from exc
            fields: list[tuple[str, str]] = []
            readonly: list[str] = []

            def walk(
                node: minidom.Element,
                prefix: str,
                fields: list[tuple[str, str]],
                readonly: list[str],
                ambiguous: bool = False,
            ) -> None:
                elements = [
                    child for child in node.childNodes if isinstance(child, minidom.Element)
                ]
                if not elements:
                    value = "".join(
                        child.data
                        for child in node.childNodes
                        if isinstance(child, (minidom.Text, minidom.CDATASection))
                    )
                    fields.append((prefix, value))
                    if ambiguous:
                        readonly.append(prefix)
                counts = Counter(child.tagName for child in elements)
                for child in elements:
                    walk(
                        child,
                        f"{prefix}/{child.tagName}" if prefix else child.tagName,
                        fields,
                        readonly,
                        ambiguous or counts[child.tagName] > 1,
                    )

            walk(entry, "", fields, readonly)
            songs.append(Song(index, song_id, tuple(fields), tuple(readonly)))
    finally:
        doc.unlink()
    return Database(content, encoding, declaration, tuple(songs))


def empty_database() -> Database:
    return parse_database(b'<?xml version="1.0" encoding="shift-jis"?>\n<mdb/>\n')


def validate_new_song(song: Song) -> None:
    """New entries must supply valid understood fields before installation."""
    understood = {spec.path for spec in SONG_FIELDS} | {
        f"difficulty/{slot.value}/{spec.path}" for slot in ChartSlot for spec in CHART_FIELDS
    }
    if understood.intersection(song.readonly_fields):
        raise PackError("A new song contains ambiguous database fields")
    values = dict(song.fields)
    required = {"info/title_name", "info/artist_name", "info/ascii", "info/bpm_min", "info/bpm_max"}
    if any(not values.get(path, "").strip() for path in required):
        raise PackError(
            "A new song is missing required title, artist, asset identity or BPM fields"
        )
    for path, value in song.fields:
        if path in understood:
            validate_value(path, value)
    if int(values["info/bpm_min"]) > int(values["info/bpm_max"]):
        raise PackError("Minimum BPM must not exceed maximum BPM")


def edit_database(
    database: Database,
    edits: tuple[FieldEdit, ...] = (),
    removed: tuple[int, ...] = (),
    additions: tuple[bytes, ...] = (),
) -> bytes:
    if any(edit.song_index < 0 or edit.song_index >= len(database.songs) for edit in edits):
        raise PackError("Song selection is stale")
    effective = tuple(
        edit for edit in edits if database.songs[edit.song_index].value(edit.path) != edit.value
    )
    if not effective and not removed and not additions:
        return database.content
    doc = _parse(database.content.decode(database.encoding))
    assert doc.documentElement is not None
    try:
        entries = _children(doc.documentElement, "music")
        for edit in effective:
            validate_value(edit.path, edit.value)
            if edit.path.endswith("/jacket_print"):
                raise PackError("Existing jacket identities are read-only")
            if edit.song_index < 0 or edit.song_index >= len(entries):
                raise PackError("Song selection is stale")
            field = _element(entries[edit.song_index], edit.path)
            if field is None or any(
                isinstance(child, minidom.Element) for child in field.childNodes
            ):
                raise PackError(f"Missing or ambiguous field is read-only: {edit.path}")
            for child in tuple(field.childNodes):
                if isinstance(child, (minidom.Text, minidom.CDATASection)):
                    field.removeChild(child)
            field.appendChild(doc.createTextNode(edit.value))
        for index in set(removed):
            if index < 0 or index >= len(entries):
                raise PackError("Song selection is stale")
            doc.documentElement.removeChild(entries[index])
        for addition in additions:
            parsed = parse_database(addition)
            source = _parse(parsed.content.decode(parsed.encoding))
            assert source.documentElement is not None
            try:
                for entry in _children(source.documentElement, "music"):
                    doc.documentElement.appendChild(doc.importNode(entry, deep=True))
            finally:
                source.unlink()
        text = re.sub(r"^<\?xml[^?]*\?>", lambda _: database.declaration, doc.toxml(), count=1)
        try:
            output = text.encode(database.encoding)
        except UnicodeError as exc:
            raise PackError("Edited text cannot be represented in the database encoding") from exc
        parse_database(output)
        return output
    finally:
        doc.unlink()
