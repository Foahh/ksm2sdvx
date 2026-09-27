"""Portable names and containment checks at filesystem boundaries."""

import hashlib
from pathlib import Path, PurePosixPath

from ksm2sdvx.packs.errors import PackError


def relative_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or str(path) != value:
        raise PackError(f"Expected a portable relative path: {value}")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    for part in path.parts:
        if (
            part in {".", ".."}
            or part.endswith((" ", "."))
            or part.split(".")[0].casefold() in reserved
            or any(ord(c) < 32 or c in ':<>"|?*' for c in part)
        ):
            raise PackError(f"Invalid path component: {part}")
    return value


def pack_name(value: str) -> str:
    relative_name(value)
    if "/" in value or value.casefold() in {"_cache", ".ksm2sdvx", "@original"}:
        raise PackError("Choose a single, non-reserved song pack folder name")
    return value


def contained(root: Path, relative: str) -> Path:
    relative_name(relative)
    candidate = root / relative
    if root.is_symlink() or root.is_junction():
        raise PackError("Linked workspace roots are not writable")
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor /= part
        if cursor.is_symlink() or cursor.is_junction():
            raise PackError(f"Linked paths are not supported: {relative}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise PackError(f"Path escapes its root: {relative}")
    return candidate


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise PackError(f"Expected a regular file: {path.name}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
