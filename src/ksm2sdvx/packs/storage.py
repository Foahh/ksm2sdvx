"""Changed-file publication with durable intent, fingerprint checks and recovery."""

import json
import os
import shutil
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from ksm2sdvx.common.jobs import JobCancelled, JobControl, Progress, checkpoint
from ksm2sdvx.packs.database import parse_database
from ksm2sdvx.packs.discovery import (
    conflicting_asset,
    database_inventory,
    files_in,
    inspect_game,
    mod_directory_names,
    tree_revision,
)
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, ChangePlan, FileChange, Recovery, Revision
from ksm2sdvx.packs.paths import contained, fingerprint, pack_name, relative_name

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@dataclass(frozen=True, slots=True)
class _Journal:
    transaction: str
    pack: str
    status: str
    changes: tuple[FileChange, ...]
    create: bool
    remove: bool
    tree: tuple[Revision, ...]
    directories: tuple[str, ...]
    step: str = ""


def _state(root: Path) -> Path:
    return contained(root, ".ksm2sdvx")


def _transactions(root: Path) -> Path:
    return contained(root, ".ksm2sdvx/transactions")


def _folder(root: Path, identifier: str) -> Path:
    relative_name(identifier)
    if "/" in identifier or not identifier.replace("-", "").isalnum():
        raise PackError("Invalid recovery identifier")
    return contained(root, f".ksm2sdvx/transactions/{identifier}")


@contextmanager
def workspace_lock(root: Path) -> Generator[None]:
    state = _state(root)
    state.mkdir(exist_ok=True)
    path = contained(root, ".ksm2sdvx/workspace.lock")
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PackError("Another manager operation is using this workspace") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, temporary.open("xb") as target:
            shutil.copyfileobj(src, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _publish(source: Path, destination: Path, scratch: Path, check: Callable[[], None]) -> None:
    # Keep incomplete copies outside the live pack, including during recovery.
    _copy(source, scratch)
    check()
    os.replace(scratch, destination)


def _save(root: Path, journal: _Journal) -> None:
    value = {
        "version": 1,
        "pack": journal.pack,
        "status": journal.status,
        "create": journal.create,
        "remove": journal.remove,
        "step": journal.step,
        "directories": journal.directories,
        "tree": [{"path": r.path, "digest": r.digest} for r in journal.tree],
        "changes": [
            {"path": c.relative, "before": c.before, "after": c.after} for c in journal.changes
        ],
    }
    _atomic_bytes(
        contained(_folder(root, journal.transaction), "journal.json"),
        json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackError("Invalid recovery record")
    return cast(dict[str, object], value)


def _strings(value: object) -> list[object]:
    if not isinstance(value, list):
        raise PackError("Invalid recovery list")
    return cast(list[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise PackError("Invalid recovery field")
    return value


def _hash(value: object) -> str | None:
    if value is None:
        return None
    text = _text(value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise PackError("Invalid recovery fingerprint")
    return text


def _load(root: Path, identifier: str) -> _Journal:
    try:
        raw: object = json.loads(contained(_folder(root, identifier), "journal.json").read_bytes())
        obj = _object(raw)
        if (
            obj.get("version") != 1
            or type(obj.get("create")) is not bool
            or type(obj.get("remove")) is not bool
        ):
            raise PackError("Unsupported recovery record")
        changes: list[FileChange] = []
        for value in _strings(obj["changes"]):
            item = _object(value)
            changes.append(
                FileChange(
                    relative_name(_text(item["path"])),
                    _hash(item["before"]),
                    _hash(item["after"]),
                    None,
                )
            )
        tree: list[Revision] = []
        for value in _strings(obj["tree"]):
            item = _object(value)
            tree.append(Revision(relative_name(_text(item["path"])), _hash(item["digest"]) or ""))
        directories = tuple(_text(value) for value in _strings(obj["directories"]))
        for name in directories:
            if name:
                relative_name(name)
        status = _text(obj["status"])
        if status not in {
            "staging",
            "prepared",
            "committing",
            "verified",
            "rolling_back",
            "rolled_back",
            "restored",
        }:
            raise PackError("Unknown recovery state")
        return _Journal(
            identifier,
            pack_name(_text(obj["pack"])),
            status,
            tuple(changes),
            bool(obj["create"]),
            bool(obj["remove"]),
            tuple(tree),
            directories,
            _text(obj.get("step", "")),
        )
    except (KeyError, ValueError, OSError) as exc:
        raise PackError(f"Cannot read recovery record {identifier}: {exc}") from exc


def _journals(root: Path) -> tuple[_Journal, ...]:
    directory = _transactions(root)
    if not directory.exists():
        return ()
    return tuple(
        _load(root, path.name)
        for path in sorted(directory.iterdir())
        if contained(directory, f"{path.name}/journal.json").is_file()
    )


def list_recovery(root: Path) -> tuple[Recovery, ...]:
    records: list[Recovery] = []
    successful: set[str] = set()
    for journal in reversed(_journals(root)):
        if journal.status == "rolled_back":
            continue
        if journal.status in {"verified", "restored"}:
            if journal.pack in successful:
                continue
            successful.add(journal.pack)
            if journal.status == "restored":
                continue
        records.append(
            Recovery(
                journal.transaction,
                journal.pack,
                journal.status,
                "Removed pack"
                if journal.remove
                else "Created pack"
                if journal.create
                else "Changed files",
            )
        )
    return tuple(records)


def _destination(root: Path, name: str) -> Path:
    return contained(root, f"data_mods/{pack_name(name)}")


def _check_file(root: Path, name: str, relative: str, allowed: set[str | None]) -> None:
    if fingerprint(contained(_destination(root, name), relative)) not in allowed:
        raise PackError(f"File changed outside the manager: {relative}")


def _prune(root: Path, keep: _Journal) -> None:
    for journal in _journals(root):
        if (
            journal.pack == keep.pack
            and journal.transaction != keep.transaction
            and journal.status in {"verified", "restored", "rolled_back"}
        ):
            folder = _folder(root, journal.transaction)
            if not folder.resolve().is_relative_to(_transactions(root).resolve()):
                raise PackError("Invalid recovery cleanup path")
            shutil.rmtree(folder)


def _check_inputs(plan: ChangePlan) -> None:
    root = plan.workspace.root
    if database_inventory(root) != plan.workspace.revisions:
        raise PackError("The installation database inventory changed; refresh and review again")
    if mod_directory_names(root) != plan.workspace.mod_directories:
        raise PackError("The installation folder inventory changed; refresh and review again")
    destination = _destination(root, plan.pack_name)
    if plan.create and destination.exists():
        raise PackError("The new pack destination appeared; choose another name")
    if not plan.create and not destination.is_dir():
        raise PackError("The selected song pack disappeared")
    for change in plan.changes:
        if fingerprint(contained(destination, change.relative)) != change.before:
            raise PackError(f"File changed outside the manager: {change.relative}")
        if change.after is not None and conflicting_asset(root, plan.pack_name, change.relative):
            raise PackError(f"Conflicting asset overlay appeared: {change.relative}")
    if plan.remove_pack and tree_revision(destination) != plan.tree:
        raise PackError("The song pack changed before removal")


def _check_restore_ids(root: Path, journal: _Journal) -> None:
    folder = _folder(root, journal.transaction)
    old_database: Path | None = None
    if journal.remove:
        candidate = contained(folder, f"deleted/{DATABASE}")
        if candidate.is_file():
            old_database = candidate
    else:
        for index, change in enumerate(journal.changes):
            if change.relative == DATABASE and change.before is not None:
                old_database = contained(folder, f"before/{index}")
    if old_database is None:
        return
    old_ids = {s.song_id for s in parse_database(old_database.read_bytes()).songs}
    current = inspect_game(root)
    existing = next((p for p in current.packs if p.name == journal.pack), None)
    current_ids = (
        {s.song_id for s in existing.database.songs}
        if existing and existing.database
        else set[int]()
    )
    introduced = old_ids - current_ids
    if introduced and not current.complete:
        raise PackError("Cannot restore song IDs while the installation inventory is incomplete")
    others = {
        s.song_id
        for p in current.packs
        if p.name != journal.pack and p.database
        for s in p.database.songs
    }
    if introduced & others:
        raise PackError("Restoration would introduce conflicting song IDs")


def _rollback(root: Path, journal: _Journal, *, restore: bool = False) -> None:
    if journal.status in {"staging", "prepared"}:
        # No live operation can precede the durable committing state.
        _save(root, replace(journal, status="rolled_back"))
        return
    destination = _destination(root, journal.pack)
    folder = _folder(root, journal.transaction)
    _check_restore_ids(root, journal)
    if journal.remove:
        backup = contained(folder, "deleted")
        if backup.exists():
            if destination.exists() or tree_revision(backup) != journal.tree:
                raise PackError("Removed pack recovery conflicts with external changes")
            _save(root, replace(journal, status="rolling_back"))
            destination.parent.mkdir(exist_ok=True)
            backup.rename(destination)
        elif tree_revision(destination) != journal.tree:
            raise PackError("The removed pack recovery copy is unavailable")
    else:
        expected_files = {c.relative for c in journal.changes if c.after is not None}
        if journal.create and set(files_in(destination)) - expected_files:
            raise PackError(
                "The created pack contains external files; recovery will not remove them"
            )
        for index, change in enumerate(journal.changes):
            actual = fingerprint(contained(destination, change.relative))
            allowed = {change.after} if restore else {change.before, change.after}
            if actual not in allowed:
                raise PackError(
                    f"Recovery stopped at an externally changed file: {change.relative}"
                )
            if (
                change.before is not None
                and fingerprint(contained(folder, f"before/{index}")) != change.before
            ):
                raise PackError("A required recovery copy is missing or changed")
        _save(root, replace(journal, status="rolling_back"))
        for index in reversed(range(len(journal.changes))):
            change = journal.changes[index]
            target = contained(destination, change.relative)
            if change.before is None:
                _check_file(root, journal.pack, change.relative, {change.before, change.after})
                target.unlink(missing_ok=True)
            elif fingerprint(target) != change.before:
                target.parent.mkdir(parents=True, exist_ok=True)
                _publish(
                    contained(folder, f"before/{index}"),
                    target,
                    folder / "publish",
                    lambda change=change: _check_file(
                        root, journal.pack, change.relative, {change.before, change.after}
                    ),
                )
        for change in journal.changes:
            if fingerprint(contained(destination, change.relative)) != change.before:
                raise PackError("Restored files failed verification")
        for name in sorted(journal.directories, key=len, reverse=True):
            directory = contained(destination, name) if name else destination
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    _save(root, replace(journal, status="restored" if restore else "rolled_back"))


def recover_pending(root: Path) -> None:
    if not _transactions(root).exists():
        return
    with workspace_lock(root):
        for journal in _journals(root):
            if journal.status not in {"verified", "restored", "rolled_back"}:
                _rollback(root, journal)


def restore_last(root: Path, transaction: str) -> None:
    with workspace_lock(root):
        if any(j.status not in {"verified", "restored", "rolled_back"} for j in _journals(root)):
            raise PackError("Recover unfinished transactions before restoring an apply")
        journal = _load(root, transaction)
        latest = next(
            (
                j
                for j in reversed(_journals(root))
                if j.pack == journal.pack and j.status in {"verified", "restored"}
            ),
            None,
        )
        if latest != journal or journal.status != "verified":
            raise PackError("Only the latest verified apply can be restored")
        _rollback(root, journal, restore=True)


def apply_changes(
    plan: ChangePlan,
    *,
    control: JobControl | None = None,
    fault: Callable[[str], None] = lambda _: None,
) -> None:
    root = plan.workspace.root
    pack_name(plan.pack_name)
    if not plan.changes and not plan.remove_pack and not plan.create:
        return
    with workspace_lock(root):
        if any(j.status not in {"verified", "restored", "rolled_back"} for j in _journals(root)):
            raise PackError("Recover the unfinished apply before making more changes")
        _check_inputs(plan)
        identifier = f"{time.time_ns():020}-{uuid.uuid4().hex}"
        folder = _folder(root, identifier)
        folder.mkdir(parents=True)
        (folder / "before").mkdir()
        (folder / "after").mkdir()
        destination = _destination(root, plan.pack_name)
        missing: set[str] = set()
        if not destination.exists():
            missing.add("")
        for change in plan.changes:
            parent = Path(change.relative).parent
            while str(parent) != ".":
                if not contained(destination, parent.as_posix()).exists():
                    missing.add(parent.as_posix())
                parent = parent.parent
        journal = _Journal(
            identifier,
            plan.pack_name,
            "staging",
            plan.changes,
            plan.create,
            plan.remove_pack,
            plan.tree,
            tuple(sorted(missing)),
        )
        published = False
        try:
            _save(root, journal)
            fault("staging")
            for index, change in enumerate(plan.changes):
                checkpoint(control, "Preparing changed files", index, len(plan.changes))
                target = contained(destination, change.relative)
                if change.before is not None:
                    _copy(target, folder / "before" / str(index))
                    if fingerprint(folder / "before" / str(index)) != change.before:
                        raise PackError("A file changed while its recovery copy was prepared")
                if change.after is not None:
                    staged = folder / "after" / str(index)
                    if isinstance(change.content, bytes):
                        _atomic_bytes(staged, change.content)
                    elif isinstance(change.content, Path):
                        _copy(change.content, staged)
                    if fingerprint(staged) != change.after:
                        raise PackError("A prepared replacement changed; review again")
                fault(f"staged:{change.relative}")
            checkpoint(control, "Ready to apply", len(plan.changes), len(plan.changes))
            _check_inputs(plan)
            journal = replace(journal, status="prepared")
            _save(root, journal)
            fault("prepared")
            journal = replace(journal, status="committing")
            _save(root, journal)
            published = True
            if control is not None:
                control.report(Progress("Committing; cancellation waits for commit or rollback"))
            if plan.remove_pack:
                fault("before:remove_pack")
                destination.rename(folder / "deleted")
                fault("after:remove_pack")
                if destination.exists() or tree_revision(folder / "deleted") != plan.tree:
                    raise PackError("Removed pack failed verification")
            else:
                for index, change in enumerate(plan.changes):
                    journal = replace(journal, step=change.relative)
                    _save(root, journal)
                    target = contained(destination, change.relative)
                    if fingerprint(target) != change.before:
                        raise PackError(f"File changed during apply: {change.relative}")
                    fault(f"before:{change.relative}")
                    if change.after is None:
                        _check_file(root, plan.pack_name, change.relative, {change.before})
                        target.unlink()
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        _publish(
                            folder / "after" / str(index),
                            target,
                            folder / "publish",
                            lambda change=change: _check_file(
                                root, plan.pack_name, change.relative, {change.before}
                            ),
                        )
                    fault(f"after:{change.relative}")
                for change in plan.changes:
                    if fingerprint(contained(destination, change.relative)) != change.after:
                        raise PackError("Published files failed verification")
            fault("before:verified")
            journal = replace(journal, status="verified")
            _save(root, journal)
        except JobCancelled:
            _save(root, replace(journal, status="rolled_back"))
            raise
        except (OSError, PackError) as exc:
            if published:
                try:
                    _rollback(root, journal)
                except (OSError, PackError) as recovery_error:
                    raise PackError(
                        f"Apply failed; recovery is required: {recovery_error}"
                    ) from exc
            else:
                _save(root, replace(journal, status="rolled_back"))
            raise PackError(f"Apply failed; installed changes were rolled back: {exc}") from exc
        # A cleanup failure must not turn a verified apply into a failed apply.
        with suppress(OSError, PackError):
            _prune(root, journal)
