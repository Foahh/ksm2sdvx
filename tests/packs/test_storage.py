from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from ksm2sdvx.common.jobs import JobCancelled, JobControl
from ksm2sdvx.packs.application import open_workspace
from ksm2sdvx.packs.discovery import inspect_game, tree_revision
from ksm2sdvx.packs.draft import create_draft, set_field
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, ChangePlan, FileChange, PackDraft, Replacement
from ksm2sdvx.packs.paths import digest
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.packs.storage import (
    apply_changes,
    list_recovery,
    recover_pending,
    restore_last,
    workspace_lock,
)
from tests.packs.helpers import assets, database, installation, song_xml, write


class Interrupted(BaseException):
    pass


def changed_plan(root: Path) -> ChangePlan:
    workspace = inspect_game(root)
    draft = set_field(PackDraft(workspace.pack("custom")), 0, "info/title_name", "Changed")
    return plan_changes(workspace, draft)


def test_apply_restore_and_original_immutability(tmp_path: Path) -> None:
    root = installation(tmp_path)
    before = tree_revision(root / "data_mods/custom")
    original = (root / "data/others/music_db.xml").read_bytes()
    apply_changes(changed_plan(root))
    record = list_recovery(root)[0]
    assert record.status == "verified"
    restore_last(root, record.transaction)
    assert tree_revision(root / "data_mods/custom") == before
    assert (root / "data/others/music_db.xml").read_bytes() == original
    assert list_recovery(root) == ()


@pytest.mark.parametrize(
    "boundary",
    [
        "staging",
        f"staged:{DATABASE}",
        "prepared",
        "before:music/new.bin",
        "after:music/new.bin",
        f"before:{DATABASE}",
        f"after:{DATABASE}",
        "before:music/old.bin",
        "after:music/old.bin",
        "before:verified",
    ],
)
@pytest.mark.parametrize("crash", [False, True])
def test_failure_at_every_live_file_transition(tmp_path: Path, boundary: str, crash: bool) -> None:
    root = installation(tmp_path)
    write(root, "data_mods/custom/music/old.bin", b"old")
    before = tree_revision(root / "data_mods/custom")
    plan = changed_plan(root)
    plan = replace(
        plan,
        changes=(
            FileChange("music/new.bin", None, digest(b"new"), b"new"),
            *plan.changes,
            FileChange("music/old.bin", digest(b"old"), None, None),
        ),
    )

    def fault(at: str) -> None:
        if at == boundary:
            if crash:
                raise Interrupted()
            raise OSError("Injected write failure")

    with pytest.raises(Interrupted if crash else PackError):
        apply_changes(plan, fault=fault)
    recover_pending(root)
    assert tree_revision(root / "data_mods/custom") == before
    assert not list_recovery(root)


def test_external_change_blocks_apply_and_restore(tmp_path: Path) -> None:
    root = installation(tmp_path)
    plan = changed_plan(root)
    target = root / "data_mods/custom" / DATABASE
    target.write_bytes(database(song_xml(title="External")))
    with pytest.raises(PackError, match="inventory"):
        apply_changes(plan)
    apply_changes(changed_plan(root))
    target.write_bytes(database(song_xml(title="After apply")))
    with pytest.raises(PackError, match="externally"):
        restore_last(root, list_recovery(root)[0].transaction)
    assert b"After apply" in target.read_bytes()


def test_latest_only_and_retire_deleted_pack(tmp_path: Path) -> None:
    root = installation(tmp_path)
    apply_changes(changed_plan(root))
    first = list_recovery(root)[0]
    workspace = inspect_game(root)
    draft = replace(PackDraft(workspace.pack("custom")), remove_pack=True)
    apply_changes(plan_changes(workspace, draft))
    assert not (root / "data_mods/custom").exists()
    records = list_recovery(root)
    assert len(records) == 1 and records[0].description == "Removed pack"
    assert not (root / ".ksm2sdvx/transactions" / first.transaction).exists()
    restore_last(root, records[0].transaction)
    assert b"Changed" in (root / "data_mods/custom" / DATABASE).read_bytes()


@pytest.mark.parametrize(
    "boundary", ["prepared", "before:remove_pack", "after:remove_pack", "before:verified"]
)
def test_interrupted_pack_removal(tmp_path: Path, boundary: str) -> None:
    root = installation(tmp_path)
    workspace = inspect_game(root)
    before = tree_revision(root / "data_mods/custom")
    plan = plan_changes(workspace, replace(PackDraft(workspace.pack("custom")), remove_pack=True))

    def fault(at: str) -> None:
        if at == boundary:
            raise Interrupted()

    with pytest.raises(Interrupted):
        apply_changes(plan, fault=fault)
    recover_pending(root)
    assert tree_revision(root / "data_mods/custom") == before


def test_create_without_mod_directory_and_restore(tmp_path: Path) -> None:
    write(tmp_path, "data/others/music_db.xml", database(song_xml(1)))
    workspace = inspect_game(tmp_path)
    apply_changes(plan_changes(workspace, create_draft(workspace, "new")))
    assert (tmp_path / "data_mods/new" / DATABASE).is_file()
    restore_last(tmp_path, list_recovery(tmp_path)[0].transaction)
    assert not (tmp_path / "data_mods/new").exists()


def test_cancel_and_workspace_writer_lock(tmp_path: Path) -> None:
    root = installation(tmp_path)
    before = tree_revision(root / "data_mods/custom")
    cancelled = Event()
    cancelled.set()
    with pytest.raises(JobCancelled):
        apply_changes(changed_plan(root), control=JobControl(cancelled))
    with workspace_lock(root), pytest.raises(PackError, match="Another manager"):
        apply_changes(changed_plan(root))
    assert tree_revision(root / "data_mods/custom") == before


def test_ambiguous_jacket_metadata_retains_possible_shared_files(tmp_path: Path) -> None:
    root = installation(tmp_path, song_xml(2), song_xml(3, jacket=2))
    assets(root / "data_mods/custom", 2)
    assets(root / "data_mods/custom", 3)
    workspace = inspect_game(root)
    draft = replace(PackDraft(workspace.pack("custom")), removed=(0,))
    plan = plan_changes(workspace, draft)
    assert not any("jk_0002" in change.relative for change in plan.changes)
    assert any(
        change.relative.endswith("0002_song2_1n.vox") and change.after is None
        for change in plan.changes
    )


def test_backup_only_changed_files(tmp_path: Path) -> None:
    root = installation(tmp_path)
    assets(root / "data_mods/custom")
    apply_changes(changed_plan(root))
    record = list_recovery(root)[0]
    backups = tuple((root / ".ksm2sdvx/transactions" / record.transaction / "before").iterdir())
    assert len(backups) == 1 and b"<mdb" in backups[0].read_bytes()


def test_blocked_recovery_opens_readonly(tmp_path: Path) -> None:
    root = installation(tmp_path)

    def crash(at: str) -> None:
        if at == "before:verified":
            raise Interrupted()

    with pytest.raises(Interrupted):
        apply_changes(changed_plan(root), fault=crash)
    write(root, f"data_mods/custom/{DATABASE}", database(song_xml(title="External")))
    workspace = open_workspace(root)
    assert workspace.recovery_error and all(pack.readonly for pack in workspace.packs)
    assert list_recovery(root)[0].status == "committing"


def test_changed_prepared_asset_is_rejected(tmp_path: Path) -> None:
    root = installation(tmp_path / "game")
    assets(root / "data_mods/custom")
    source = write(tmp_path, "replacement.s3v", b"prepared")
    workspace = inspect_game(root)
    draft = replace(
        PackDraft(workspace.pack("custom")),
        replacements=(
            Replacement("music/0002_song2/0002_song2_1n.s3v", source, digest(b"prepared")),
        ),
    )
    source.write_bytes(b"changed")
    with pytest.raises(PackError, match="prepared asset changed"):
        plan_changes(workspace, draft)
