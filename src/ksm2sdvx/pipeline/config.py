"""Explicit song grouping and portable TOML package configuration."""

import math
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from ksm2sdvx.metadata.models import MAX_SONG_ID, ChartRadar
from ksm2sdvx.pipeline.errors import PackageError


@dataclass(frozen=True, slots=True)
class JacketConfig:
    source: Path | None = None
    author: str | None = None


@dataclass(frozen=True, slots=True)
class ChartInput:
    path: Path
    slot: str
    jacket: JacketConfig = JacketConfig()
    level_tenths: int | None = None
    max_exscore: int | None = None
    price: int | None = None
    limited: int | None = None
    jacket_print: int = -2
    jacket_mask: int = 0
    radar: ChartRadar = ChartRadar()


@dataclass(frozen=True, slots=True)
class PackageConfig:
    """Package settings with a source root derived from the TOML directory."""

    name: str
    root: Path
    song_id: int
    charts: tuple[ChartInput, ...]
    title: str | None = None
    artist: str | None = None
    title_yomigana: str | None = None
    artist_yomigana: str | None = None
    volume: int | None = None
    version: int | None = None
    distribution_date: date | None = None
    bg_no: int = 2
    genre: int = 0
    is_fixed: int = 1
    demo_pri: int = 0
    inf_ver: int | None = None
    license_text: str | None = None
    jacket: JacketConfig = JacketConfig()
    target_lufs: float = -11.0
    true_peak_dbtp: float = -1.0


def _table(value: object, location: str, allowed: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackageError(f"{location} must be a TOML table")
    table = cast(dict[str, object], value)
    unknown = table.keys() - allowed
    if unknown:
        raise PackageError(f"Unknown {location} option: {', '.join(sorted(unknown))}")
    return table


def _string(table: dict[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PackageError(f"{key} must be a nonempty string")
    return value


def _optional_string(table: dict[str, object], key: str) -> str | None:
    return _string(table, key) if key in table else None


def _integer(
    table: dict[str, object],
    key: str,
    minimum: int = 1,
    *,
    maximum: int | None = None,
    default: int | None = None,
) -> int:
    value = table.get(key, default)
    if type(value) is not int or value < minimum:
        raise PackageError(f"{key} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise PackageError(f"{key} must be an integer <= {maximum}")
    return value


def _optional_integer(table: dict[str, object], key: str) -> int | None:
    return _integer(table, key, 0) if key in table else None


def _distribution_date(table: dict[str, object]) -> date | None:
    if "distribution_date" not in table:
        return None
    value = _integer(table, "distribution_date", 10000101, maximum=99991231)
    try:
        return date(value // 10000, value // 100 % 100, value % 100)
    except ValueError as exc:
        raise PackageError("distribution_date must be a valid YYYYMMDD date") from exc


def _radar(value: object) -> ChartRadar:
    radar = _table(
        value, "charts.radar", {"notes", "peak", "tsumami", "tricky", "hand_trip", "one_hand"}
    )
    values = {key: _integer(radar, key, 0, maximum=65535) for key in radar}
    return ChartRadar(
        notes=values.get("notes"),
        peak=values.get("peak"),
        tsumami=values.get("tsumami"),
        tricky=values.get("tricky"),
        hand_trip=values.get("hand_trip"),
        one_hand=values.get("one_hand"),
    )


def _number(table: dict[str, object], key: str, default: float) -> float:
    value = table.get(key, default)
    if type(value) not in (int, float):
        raise PackageError(f"{key} must be a finite number")
    try:
        number = float(cast(int | float, value))
    except OverflowError as exc:
        raise PackageError(f"{key} must be a finite number") from exc
    if not math.isfinite(number):
        raise PackageError(f"{key} must be a finite number")
    return number


def _source_path(root: Path, name: str) -> Path:
    relative = Path(name.replace("\\", "/"))
    if relative.is_absolute() or ":" in name:
        raise PackageError("Chart and jacket paths must be relative to the source root")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise PackageError("Source path escapes the package root")
    return path


def _jacket_config(value: object, root: Path) -> JacketConfig:
    jacket = _table(value, "jacket", {"source", "author"})
    source = _optional_string(jacket, "source")
    return JacketConfig(
        source=_source_path(root, source) if source else None,
        author=_optional_string(jacket, "author"),
    )


def parse_package_config(text: str, *, base: Path) -> PackageConfig:
    """Parse TOML using its containing directory as the source root."""
    try:
        raw: object = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PackageError(f"Invalid package TOML: {exc}") from exc
    data = _table(
        raw,
        "package",
        {
            "name",
            "song_id",
            "charts",
            "metadata",
            "music",
            "jacket",
        },
    )
    name = _string(data, "name")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
        raise PackageError("name must contain only ASCII letters, digits, '_' and '-'")
    root = base.resolve()
    charts_value = data.get("charts")
    if not isinstance(charts_value, list) or not charts_value:
        raise PackageError("At least one [[charts]] entry is required")
    charts: list[ChartInput] = []
    slots: set[str] = set()
    for value in cast(list[object], charts_value):
        chart = _table(
            value,
            "charts",
            {
                "path",
                "slot",
                "jacket",
                "level_tenths",
                "max_exscore",
                "price",
                "limited",
                "jacket_print",
                "jacket_mask",
                "radar",
            },
        )
        slot = _string(chart, "slot")
        if slot not in {"novice", "advanced", "exhaust", "infinite", "maximum", "ultimate"}:
            raise PackageError(f"Unknown chart slot: {slot}")
        if slot in slots:
            raise PackageError(f"Duplicate chart slot: {slot}")
        slots.add(slot)
        charts.append(
            ChartInput(
                path=_source_path(root, _string(chart, "path")),
                slot=slot,
                jacket=_jacket_config(chart.get("jacket", {}), root),
                level_tenths=_optional_integer(chart, "level_tenths"),
                max_exscore=_optional_integer(chart, "max_exscore"),
                price=_integer(chart, "price", -(2**31)) if "price" in chart else None,
                limited=_optional_integer(chart, "limited"),
                jacket_print=_integer(
                    chart, "jacket_print", -(2**31), maximum=2**31 - 1, default=-2
                ),
                jacket_mask=_integer(chart, "jacket_mask", -(2**31), maximum=2**31 - 1, default=0),
                radar=_radar(chart.get("radar", {})),
            )
        )
    metadata = _table(
        data.get("metadata", {}),
        "metadata",
        {
            "title",
            "artist",
            "title_yomigana",
            "artist_yomigana",
            "volume",
            "version",
            "distribution_date",
            "bg_no",
            "genre",
            "is_fixed",
            "demo_pri",
            "inf_ver",
            "license_text",
        },
    )
    music = _table(data.get("music", {}), "music", {"target_lufs", "true_peak_dbtp"})
    return PackageConfig(
        name=name,
        root=root,
        song_id=_integer(data, "song_id", maximum=MAX_SONG_ID),
        charts=tuple(charts),
        title=_optional_string(metadata, "title"),
        artist=_optional_string(metadata, "artist"),
        title_yomigana=_optional_string(metadata, "title_yomigana"),
        artist_yomigana=_optional_string(metadata, "artist_yomigana"),
        volume=_optional_integer(metadata, "volume"),
        version=_optional_integer(metadata, "version"),
        distribution_date=_distribution_date(metadata),
        bg_no=_integer(metadata, "bg_no", 0, maximum=65535, default=2),
        genre=_integer(metadata, "genre", 0, maximum=2**32 - 1, default=0),
        is_fixed=_integer(metadata, "is_fixed", 0, maximum=255, default=1),
        demo_pri=_integer(metadata, "demo_pri", -128, maximum=127, default=0),
        inf_ver=_integer(metadata, "inf_ver", 0, maximum=255) if "inf_ver" in metadata else None,
        license_text=_optional_string(metadata, "license_text"),
        jacket=_jacket_config(data.get("jacket", {}), root),
        target_lufs=_number(music, "target_lufs", -11.0),
        true_peak_dbtp=_number(music, "true_peak_dbtp", -1.0),
    )


def load_package_config(path: Path) -> PackageConfig:
    """Load a configuration with source paths relative to its own directory."""
    try:
        return parse_package_config(
            path.read_text(encoding="utf-8-sig"), base=path.resolve().parent
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise PackageError(f"Cannot load package configuration: {exc}") from exc
