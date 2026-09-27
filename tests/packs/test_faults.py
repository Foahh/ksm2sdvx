import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

import pytest

from ksm2sdvx.packs.discovery import inspect_game, tree_revision
from ksm2sdvx.packs.draft import set_field
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, FileChange, PackDraft, Replacement
from ksm2sdvx.packs.paths import digest
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.packs.storage import apply_changes, list_recovery, recover_pending
from tests.packs.helpers import assets, installation, write
from tests.packs.test_storage import changed_plan


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_windows_file_lock_rolls_back(tmp_path: Path) -> None:
    root = installation(tmp_path)
    before = tree_revision(root / "data_mods/custom")
    plan = changed_plan(root)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # Allow backup reads but deny replacement/deletion while the handle is held.
    handle = create(str(root / "data_mods/custom" / DATABASE), 0x80000000, 1, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    try:
        with pytest.raises(PackError, match="rolled back"):
            apply_changes(plan)
    finally:
        close(handle)
    assert tree_revision(root / "data_mods/custom") == before
    assert not list_recovery(root)


@pytest.mark.parametrize("after_restore", [False, True])
def test_failure_during_rollback_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_restore: bool
) -> None:
    root = installation(tmp_path)
    write(root, "data_mods/custom/music/existing.bin", b"old")
    before = tree_revision(root / "data_mods/custom")
    plan = changed_plan(root)
    plan = replace(
        plan,
        changes=(
            FileChange("music/existing.bin", digest(b"old"), digest(b"new"), b"new"),
            *plan.changes,
        ),
    )

    def broken(source: Path, target: Path, scratch: Path, check: Callable[[], None]) -> None:
        if after_restore:
            check()
            target.write_bytes(source.read_bytes())
        raise PermissionError("Recovery file temporarily locked")

    def fail(at: str) -> None:
        if at == "after:music/existing.bin":
            monkeypatch.setattr("ksm2sdvx.packs.storage._publish", broken)
            raise OSError("Injected publication failure")

    with pytest.raises(PackError, match="recovery is required"):
        apply_changes(plan, fault=fail)
    assert list_recovery(root)[0].status == "rolling_back"
    monkeypatch.undo()
    recover_pending(root)
    assert tree_revision(root / "data_mods/custom") == before


def test_external_change_between_stage_and_replace_is_preserved(tmp_path: Path) -> None:
    root = installation(tmp_path)
    target = root / "data_mods/custom" / DATABASE
    plan = changed_plan(root)

    def external(at: str) -> None:
        if at == f"before:{DATABASE}":
            target.write_bytes(b"external editor's content")

    with pytest.raises(PackError, match="recovery is required"):
        apply_changes(plan, fault=external)
    assert target.read_bytes() == b"external editor's content"


def test_new_mod_directory_invalidates_review(tmp_path: Path) -> None:
    root = installation(tmp_path)
    plan = changed_plan(root)
    (root / "data_mods/external").mkdir()
    with pytest.raises(PackError, match="folder inventory"):
        apply_changes(plan)


def test_cross_pack_overlay_and_referenced_jacket_protection(tmp_path: Path) -> None:
    root = installation(tmp_path)
    assets(root / "data_mods/custom")
    relative = "music/0002_song2/0002_song2_1n.s3v"
    write(root, f"data_mods/overlay/{relative}", b"other pack")
    source = write(tmp_path, "prepared.s3v", b"replacement")
    workspace = inspect_game(root)
    draft = replace(
        PackDraft(workspace.pack("custom")),
        replacements=(Replacement(relative, source, digest(b"replacement")),),
    )
    with pytest.raises(PackError, match="conflicting overlay"):
        plan_changes(workspace, draft)


def test_enabling_chart_without_inputs_is_blocked(tmp_path: Path) -> None:
    root = installation(tmp_path)
    target = root / "data_mods/custom" / DATABASE
    target.write_bytes(target.read_bytes().replace(b"<difnum>50", b"<difnum>0"))
    workspace = inspect_game(root)
    draft = set_field(PackDraft(workspace.pack("custom")), 0, "difficulty/novice/difnum", "50")
    with pytest.raises(PackError, match="requires a loose asset"):
        plan_changes(workspace, draft)
