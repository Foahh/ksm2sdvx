from pathlib import Path

import pytest

from ksm2sdvx.packs.discovery import inspect_game
from ksm2sdvx.packs.draft import set_field
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import PackDraft
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.packs.storage import apply_changes, list_recovery, restore_last
from tests.packs.helpers import installation
from tests.packs.test_storage import changed_plan


def test_failed_cleanup_never_exposes_superseded_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = installation(tmp_path)

    def locked_cleanup(*_: object) -> None:
        raise PermissionError("Recovery directory temporarily locked")

    monkeypatch.setattr("ksm2sdvx.packs.storage._prune", locked_cleanup)
    apply_changes(changed_plan(root))
    first = list_recovery(root)[0]
    workspace = inspect_game(root)
    draft = set_field(PackDraft(workspace.pack("custom")), 0, "info/title_name", "Next apply")
    apply_changes(plan_changes(workspace, draft))
    records = list_recovery(root)
    assert len(records) == 1 and records[0].transaction != first.transaction
    restore_last(root, records[0].transaction)
    assert not list_recovery(root)
    with pytest.raises(PackError, match="latest verified"):
        restore_last(root, first.transaction)
