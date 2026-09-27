from dataclasses import replace
from pathlib import Path
from xml.dom import minidom

import pytest

from ksm2sdvx.packs.database import edit_database, parse_database
from ksm2sdvx.packs.discovery import inspect_game
from ksm2sdvx.packs.draft import create_draft, next_song_id, set_field, validate_draft
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import ORIGINAL, FieldEdit, PackDraft, PreparedSong
from tests.packs.helpers import database, installation, song_xml, write


def test_noop_and_unknown_xml_preservation() -> None:
    content = database(song_xml(title="日本語"), song_xml(3))
    parsed = parse_database(content)
    assert edit_database(parsed) == content
    assert edit_database(parsed, (FieldEdit(0, "info/title_name", "日本語"),)) == content
    output = edit_database(parsed, (FieldEdit(0, "info/title_name", "変更"),))
    decoded = output.decode("cp932")
    assert "<?custom keep?>" in decoded and "<!-- database comment -->" in decoded
    assert "<!-- retained between sections -->" in decoded
    assert '<unknown x="1"><child>untouched</child></unknown>' in decoded
    assert '<music id="2" custom="keep">' in decoded
    assert parse_database(output).songs[1] == parsed.songs[1]
    assert decoded.index("<info>") < decoded.index("<unknown") < decoded.index("<difficulty>")
    assert parse_database(output).encoding == "cp932"


def test_encoding_failure_never_changes_source() -> None:
    parsed = parse_database(database(song_xml()))
    with pytest.raises(PackError, match="encoding"):
        edit_database(parsed, (FieldEdit(0, "info/title_name", "🎼"),))
    assert parsed.songs[0].title == "Song"
    utf = parse_database(database(song_xml(), encoding="utf-8"))
    assert (
        parse_database(edit_database(utf, (FieldEdit(0, "info/title_name", "🎼"),))).songs[0].title
        == "🎼"
    )


@pytest.mark.parametrize(
    "content",
    [
        b"\x00\xff",
        b'<!DOCTYPE mdb [<!ENTITY x "y">]><mdb/>',
        b"<other/>",
        b'<?xml version="1.0" encoding="utf-16"?><mdb/>',
    ],
)
def test_unsupported_database(content: bytes) -> None:
    with pytest.raises(PackError):
        parse_database(content)


def test_ambiguous_field_is_readonly() -> None:
    parsed = parse_database(
        database(song_xml().replace("</info>", "<title_name>Other</title_name></info>"))
    )
    assert len([p for p, _ in parsed.songs[0].fields if p == "info/title_name"]) == 2
    with pytest.raises(PackError, match="ambiguous"):
        edit_database(parsed, (FieldEdit(0, "info/title_name", "Changed"),))


def test_original_is_immutable_and_missing_mods_allowed(tmp_path: Path) -> None:
    original = write(tmp_path, "data/others/music_db.xml", database(song_xml(1)))
    before = original.read_bytes()
    snapshot = inspect_game(tmp_path)
    assert len(snapshot.packs) == 1 and not (tmp_path / "data_mods").exists()
    with pytest.raises(PackError, match="read-only"):
        set_field(PackDraft(snapshot.pack(ORIGINAL)), 0, "info/title_name", "Changed")
    assert create_draft(snapshot, "new").dirty
    assert original.read_bytes() == before


def test_duplicates_and_reservations(tmp_path: Path) -> None:
    installation(tmp_path, song_xml(2), song_xml(2, "Duplicate"))
    snapshot = inspect_game(tmp_path)
    draft = PackDraft(snapshot.pack("custom"))
    assert draft.pack.database is not None and len(draft.pack.database.songs) == 2
    with pytest.raises(PackError, match="conflicting"):
        validate_draft(snapshot, set_field(draft, 1, "info/title_name", "Edit"))
    draft = replace(draft, additions=(PreparedSong(database(song_xml(3)), ()),))
    assert next_song_id(snapshot, draft) == 4


def test_pending_song_edit_preserves_identity(tmp_path: Path) -> None:
    snapshot = inspect_game(installation(tmp_path))
    draft = replace(
        PackDraft(snapshot.pack("custom")), additions=(PreparedSong(database(song_xml(3)), ()),)
    )
    edited = set_field(draft, 1, "info/title_name", "Pending")
    parsed = parse_database(edited.additions[0].database)
    assert parsed.songs[0].song_id == 3 and parsed.songs[0].title == "Pending"
    with pytest.raises(PackError, match="not editable"):
        set_field(edited, 1, "info/ascii", "other")


def test_unknown_nodes_equivalent_after_edit() -> None:
    content = database(song_xml()).replace(b'<unknown x="1">', b'<unknown x="1" y="2">')
    before = minidom.parseString(content.decode("cp932"))
    after = minidom.parseString(
        edit_database(parse_database(content), (FieldEdit(0, "info/volume", "80"),)).decode("cp932")
    )
    assert (
        before.getElementsByTagName("unknown")[0].toxml()
        == after.getElementsByTagName("unknown")[0].toxml()
    )
