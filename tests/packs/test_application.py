from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from ksm2sdvx.chart import ConversionOptions, VoxProfile
from ksm2sdvx.common.jobs import JobCancelled, JobControl
from ksm2sdvx.packs.application import add_prepared, export_pack, prepare_generated, remove_song
from ksm2sdvx.packs.discovery import inspect_game, tree_revision
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, PackDraft
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.packs.storage import apply_changes
from ksm2sdvx.pipeline.build import build_package
from ksm2sdvx.pipeline.config import ChartInput, PackageConfig
from tests.packs.helpers import assets, database, installation, song_xml, write


def generated(root: Path, song_id: int = 3) -> Path:
    write(root, DATABASE, database(song_xml(song_id)))
    write(root, "ksm2sdvx-report.json", b'{"schema_version":1}')
    assets(root, song_id)
    return root


def test_generated_import_edit_apply_export(tmp_path: Path) -> None:
    root = installation(tmp_path / "game")
    source = generated(tmp_path / "source")
    prepared = prepare_generated(source, tmp_path / "prepared")
    workspace = inspect_game(root)
    draft = add_prepared(workspace, PackDraft(workspace.pack("custom")), prepared)
    assert draft.dirty and not (root / "data_mods/custom/music/0003_song3").exists()
    apply_changes(plan_changes(workspace, draft))
    current = inspect_game(root)
    pack = current.pack("custom")
    assert pack.database is not None and len(pack.database.songs) == 2
    destination = export_pack(current, pack, tmp_path / "export")
    assert tree_revision(destination) == tree_revision(root / "data_mods/custom")
    with pytest.raises(PackError, match="new export"):
        export_pack(current, pack, root / "another-pack")


def test_import_missing_inputs_collision_and_cancel(tmp_path: Path) -> None:
    root = installation(tmp_path / "game")
    source = generated(tmp_path / "source", 2)
    prepared = prepare_generated(source, tmp_path / "prepared")
    workspace = inspect_game(root)
    draft = PackDraft(workspace.pack("custom"))
    with pytest.raises(PackError, match="unavailable"):
        add_prepared(workspace, draft, prepared)
    (source / "music/0002_song2/0002_song2_1n.vox").unlink()
    with pytest.raises(PackError, match="missing required"):
        prepare_generated(source, tmp_path / "prepared")
    source = generated(tmp_path / "cancel-source")
    event = Event()
    event.set()
    with pytest.raises(JobCancelled):
        prepare_generated(source, tmp_path / "prepared", control=JobControl(event))
    assert not draft.dirty


def test_remove_pending_song(tmp_path: Path) -> None:
    workspace = inspect_game(installation(tmp_path / "game"))
    prepared = prepare_generated(generated(tmp_path / "source"), tmp_path / "prepared")
    draft = replace(PackDraft(workspace.pack("custom")), additions=(prepared,))
    assert not remove_song(draft, 1).dirty


@pytest.mark.parametrize(
    "old,new",
    [
        (b"<volume>91", b"<volume>invalid"),
        (b"<bpm_min>12000", b"<bpm_min>13000"),
        (b'<artist_name __type="str">Artist', b'<artist_name __type="str">'),
    ],
)
def test_generated_import_blocks_invalid_fields(tmp_path: Path, old: bytes, new: bytes) -> None:
    source = generated(tmp_path / "source")
    path = source / DATABASE
    path.write_bytes(path.read_bytes().replace(old, new))
    with pytest.raises(PackError):
        prepare_generated(source, tmp_path / "prepared")


def test_pipeline_cancellation_before_parsing(tmp_path: Path) -> None:
    event = Event()
    event.set()
    config = PackageConfig("song", tmp_path, 1, (ChartInput(tmp_path / "missing.kson", "novice"),))
    with pytest.raises(JobCancelled):
        build_package(
            config,
            destination=tmp_path / "output",
            options=ConversionOptions(),
            profile=VoxProfile(),
            control=JobControl(event),
        )
    assert not (tmp_path / "output").exists()
