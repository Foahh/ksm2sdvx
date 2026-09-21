"""Immutable music database XML and strict text decoding."""

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from ksm2sdvx.metadata.errors import MetadataError


@dataclass(frozen=True, slots=True)
class XmlElement:
    name: str
    attributes: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    children: tuple[XmlElement, ...] = ()

    def child(self, name: str) -> XmlElement:
        matches = tuple(child for child in self.children if child.name == name)
        if len(matches) != 1:
            raise MetadataError(f"Expected exactly one {name!r} element in {self.name!r}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class MusicDatabaseEntry:
    song_id: int
    element: XmlElement


@dataclass(frozen=True, slots=True)
class MusicDatabase:
    entries: tuple[MusicDatabaseEntry, ...]
    attributes: tuple[tuple[str, str], ...] = ()

    @property
    def song_ids(self) -> frozenset[int]:
        return frozenset(entry.song_id for entry in self.entries)

    def entry(self, song_id: int) -> MusicDatabaseEntry:
        matches = tuple(entry for entry in self.entries if entry.song_id == song_id)
        if len(matches) != 1:
            raise MetadataError(f"Expected exactly one database entry for song ID {song_id}")
        return matches[0]


def from_element(element: ET.Element[str]) -> XmlElement:
    text = element.text if element.text and element.text.strip() else None
    return XmlElement(
        element.tag,
        tuple(element.attrib.items()),
        text,
        tuple(from_element(child) for child in element),
    )


def to_element(element: XmlElement) -> ET.Element[str]:
    result = ET.Element(element.name, dict(element.attributes))
    result.text = element.text
    result.extend(to_element(child) for child in element.children)
    return result


def parse_music_database(text: str) -> MusicDatabase:
    """Parse a decoded database, preserving its entry fields and XML types."""
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise MetadataError(
            "Music database XML must not contain document type or entity declarations"
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MetadataError(f"Cannot parse music database XML: {exc}") from exc
    if root.tag != "mdb":
        raise MetadataError("Music database root must be <mdb>")
    entries: list[MusicDatabaseEntry] = []
    seen: set[int] = set()
    for element in root:
        raw_id = element.get("id", "")
        if element.tag != "music" or not raw_id.isascii() or not raw_id.isdigit():
            raise MetadataError("Database children must be <music> elements with integer IDs")
        song_id = int(raw_id)
        if song_id <= 0 or song_id in seen:
            raise MetadataError(f"Database song ID {song_id} is nonpositive or duplicated")
        seen.add(song_id)
        entry = from_element(element)
        entry.child("info")
        entry.child("difficulty")
        entries.append(MusicDatabaseEntry(song_id, entry))
    return MusicDatabase(tuple(entries), tuple(root.attrib.items()))


def load_music_database(path: Path) -> MusicDatabase:
    """Read UTF-8 or Windows Shift-JIS music database XML."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MetadataError(f"Cannot read music database {path}: {exc}") from exc
    declaration = re.search(rb"<\?xml\s[^>]*encoding=[\"']([^\"']+)[\"']", data[:256])
    encoding = (
        declaration.group(1).decode("ascii", errors="replace").lower() if declaration else "utf-8"
    )
    if encoding in {"shift-jis", "shift_jis", "sjis", "windows-31j", "cp932"}:
        codec = "cp932"
    elif encoding in {"utf-8", "utf8"}:
        codec = "utf-8-sig"
    else:
        raise MetadataError(f"Unsupported music database XML encoding: {encoding}")
    try:
        return parse_music_database(data.decode(codec))
    except UnicodeError as exc:
        raise MetadataError(f"Cannot decode music database as {encoding}: {exc}") from exc
