"""Read-only installation and loose-asset discovery."""

from pathlib import Path

from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.common.jobs import JobControl, checkpoint
from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.database import parse_database
from ksm2sdvx.packs.errors import PackError
from ksm2sdvx.packs.models import DATABASE, ORIGINAL, Asset, Pack, Revision, Workspace
from ksm2sdvx.packs.paths import contained, fingerprint, pack_name, relative_name


def problem(code: str, message: str, source: str = "") -> Diagnostic:
    return Diagnostic(code, Severity.ERROR, Stage.INSPECT, message, "song_pack", source_path=source)


def database_inventory(root: Path) -> tuple[Revision, ...]:
    paths = [contained(root, "data/others/music_db.xml")]
    mods = contained(root, "data_mods")
    if mods.exists():
        for folder in sorted(mods.iterdir(), key=lambda p: p.name.casefold()):
            if folder.name == "_cache":
                continue
            contained(root, f"data_mods/{folder.name}")
            if folder.is_dir():
                paths.extend(
                    contained(root, f"data_mods/{folder.name}/others/{name}")
                    for name in ("music_db.xml", "music_db.merged.xml")
                )
    return tuple(
        Revision(path.relative_to(root).as_posix(), value)
        for path in paths
        if (value := fingerprint(path)) is not None
    )


def mod_directory_names(root: Path) -> tuple[str, ...]:
    mods = contained(root, "data_mods")
    return (
        tuple(
            sorted(
                folder.name
                for folder in mods.iterdir()
                if folder.is_dir() and folder.name.casefold() != "_cache"
            )
        )
        if mods.exists()
        else ()
    )


def inspect_game(root: Path, *, control: JobControl | None = None) -> Workspace:
    if root.is_symlink() or root.is_junction():
        raise PackError("Choose the installation directory, not a linked folder")
    root = root.resolve()
    base = contained(root, "data/others/music_db.xml")
    if not base.is_file():
        raise PackError("Select the game folder containing data/others/music_db.xml")
    checkpoint(control, "Inspecting game folder")
    packs: list[Pack] = []
    complete = True
    revisions = database_inventory(root)
    grouped: dict[str, list[Revision]] = {}
    for revision in revisions:
        name = ORIGINAL if revision.path.startswith("data/") else revision.path.split("/")[1]
        grouped.setdefault(name, []).append(revision)
    for name, records in grouped.items():
        checkpoint(control, f"Reading {'original songs' if name == ORIGINAL else name}")
        record = next((r for r in records if r.path.endswith(DATABASE)), records[0])
        diagnostics: list[Diagnostic] = []
        parsed = None
        try:
            parsed = parse_database(contained(root, record.path).read_bytes())
        except (PackError, OSError, UnicodeError) as exc:
            complete = False
            diagnostics.append(problem("PACK_DATABASE_UNREADABLE", str(exc), record.path))
        # Reserve IDs from full replacements too, but never guess which database wins.
        readonly = name == ORIGINAL or len(records) != 1 or not record.path.endswith(DATABASE)
        if name != ORIGINAL and readonly:
            complete = False
            diagnostics.append(
                problem(
                    "PACK_DATABASE_OVERRIDE", "Full database overrides are read-only", record.path
                )
            )
        packs.append(Pack(name, parsed, readonly, tuple(diagnostics)))
    return Workspace(
        root, tuple(packs), revisions, complete, mod_directories=mod_directory_names(root)
    )


def pack_root(workspace: Workspace, pack: Pack) -> Path:
    if pack.name == ORIGINAL:
        return contained(workspace.root, "data")
    return contained(workspace.root, f"data_mods/{pack_name(pack.name)}")


def files_in(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    result: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        contained(root, relative)
        if path.is_file():
            result.append(relative)
    return tuple(result)


def tree_revision(root: Path) -> tuple[Revision, ...]:
    return tuple(
        Revision(name, fingerprint(contained(root, name)) or "") for name in files_in(root)
    )


def conflicting_asset(root: Path, name: str, relative: str) -> bool:
    """Loose overlays with unknown precedence cannot be replaced safely."""
    if not relative.startswith(("music/", "graphics/")):
        return False
    if contained(root, f"data/{relative}").exists():
        return True
    mods = contained(root, "data_mods")
    if not mods.is_dir():
        return False
    return any(
        contained(root, f"data_mods/{folder.name}/{relative}").exists()
        for folder in mods.iterdir()
        if folder.is_dir() and folder.name.casefold() not in {name.casefold(), "_cache"}
    )


def external_jacket_references(workspace: Workspace, name: str) -> set[int]:
    """Conservatively guard potential references without redirecting asset paths."""
    return {
        int(value)
        for pack in workspace.packs
        if pack.name != name and pack.database
        for song in pack.database.songs
        for path, value in song.fields
        if path.endswith("/jacket_print") and value.isdecimal() and int(value) > 0
    }


def discover_assets(
    workspace: Workspace, pack: Pack, *, root: Path | None = None
) -> tuple[Asset, ...]:
    if pack.database is None:
        return ()
    root = root if root is not None else pack_root(workspace, pack)
    found = set(files_in(root))
    candidates: dict[str, tuple[str, list[int]]] = {}
    selector_dirs = sorted(
        {
            str(Path(name).parent).replace("\\", "/")
            for name in found
            if name.startswith("graphics/s_jacket")
        }
    ) or ["graphics/s_jacket00_ifs"]
    for song in pack.database.songs:
        try:
            stem = relative_name(song.stem)
            if "/" in stem or not song.value("info/ascii"):
                continue
        except PackError:
            continue
        directory = f"music/{stem}"
        names: dict[str, str] = {}
        for slot in ChartSlot:
            level = song.value(f"difficulty/{slot.value}/difnum", "0")
            if level in {"", "0"}:
                continue
            names[f"{directory}/{stem}_{slot.suffix}.vox"] = "Chart"
            audio = [
                f"{directory}/{stem}_{slot.suffix}{extension}" for extension in (".s3v", ".2dx")
            ]
            audio += [f"{directory}/{stem}{extension}" for extension in (".s3v", ".2dx")]
            available = [name for name in audio if name in found]
            names.update((name, "Gameplay audio") for name in (available or audio[:1]))
            sampler = f"{directory}/general_sampler_{slot.suffix}.s3p"
            if sampler in found:
                names[sampler] = "Sampler"
            # Only conventional filenames establish asset identity. Unfamiliar
            # database values must not redirect a replacement to another song.
            jacket_id = song.song_id
            jacket_directory = directory
            for suffix in ("", "_s", "_b"):
                names[f"{jacket_directory}/jk_{jacket_id:04}_{slot.number}{suffix}.png"] = "Jacket"
            for selector in selector_dirs:
                names[f"{selector}/jk_{jacket_id:04}_{slot.number}_t.png"] = "Selector jacket"
        preview = [f"{directory}/{stem}_pre{extension}" for extension in (".s3v", ".2dx")]
        names.update(
            (name, "Preview audio") for name in ([n for n in preview if n in found] or preview[:1])
        )
        for name, kind in names.items():
            if name not in candidates:
                candidates[name] = (kind, [])
            candidates[name][1].append(song.index)
    return tuple(
        Asset(name, kind, name in found, tuple(owners))
        for name, (kind, owners) in sorted(candidates.items())
    )
