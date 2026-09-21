"""Per-chart metadata and typed target payloads."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath

from ksm2sdvx.common.diagnostics import Diagnostic
from ksm2sdvx.common.types import JsonValue, Milliseconds
from ksm2sdvx.metadata.database import MusicDatabase, XmlElement
from ksm2sdvx.metadata.errors import MetadataError

# Upper bound for ordinary song IDs in the supported target's song tables.
MAX_SONG_ID = 3071


@dataclass(frozen=True, slots=True)
class MetadataField:
    json_pointer: str
    value: JsonValue


@dataclass(frozen=True, slots=True)
class ChartMetadata:
    source: Path
    title: str
    artist: str
    chart_author: str
    difficulty: int | str
    level: int
    display_bpm: str
    audio_offset: Milliseconds
    preview_offset: Milliseconds
    preview_duration: Milliseconds
    retained: tuple[MetadataField, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    """Separate metadata for every chart; no implicit shared-song values."""

    charts: tuple[ChartMetadata, ...]


@dataclass(frozen=True, slots=True)
class MetadataResult[TargetT]:
    metadata: TargetT
    diagnostics: tuple[Diagnostic, ...] = ()


class ChartSlot(StrEnum):
    NOVICE = "novice"
    ADVANCED = "advanced"
    EXHAUST = "exhaust"
    INFINITE = "infinite"
    MAXIMUM = "maximum"
    ULTIMATE = "ultimate"

    @property
    def number(self) -> int:
        return tuple(ChartSlot).index(self) + 1

    @property
    def suffix(self) -> str:
        return f"{self.number}{self.value[0]}"


@dataclass(frozen=True, slots=True)
class ChartRadar:
    notes: int | None = None
    peak: int | None = None
    tsumami: int | None = None
    tricky: int | None = None
    hand_trip: int | None = None
    one_hand: int | None = None

    def items(self) -> tuple[tuple[str, int | None], ...]:
        return (
            ("notes", self.notes),
            ("peak", self.peak),
            ("tsumami", self.tsumami),
            ("tricky", self.tricky),
            ("hand-trip", self.hand_trip),
            ("one-hand", self.one_hand),
        )

    @property
    def complete(self) -> bool:
        return all(value is not None for _, value in self.items())


@dataclass(frozen=True, slots=True)
class ChartAssignment:
    source: Path
    slot: ChartSlot
    jacket_author: str | None = None
    level_tenths: int | None = None
    max_exscore: int | None = None
    price: int | None = None
    limited: int | None = None
    jacket_print: int = -2
    jacket_mask: int = 0
    radar: ChartRadar = ChartRadar()


@dataclass(frozen=True, slots=True)
class SdvxMetadataSettings:
    database: MusicDatabase
    song_id: int
    charts: tuple[ChartAssignment, ...]
    ascii_name: str | None = None
    title: str | None = None
    artist: str | None = None
    bpm_min: float | None = None
    bpm_max: float | None = None
    title_yomigana: str | None = None
    artist_yomigana: str | None = None
    volume: int = 91
    version: int = 7
    distribution_date: date = field(default_factory=date.today)
    bg_no: int = 2
    genre: int = 0
    is_fixed: int = 1
    demo_pri: int = 0
    inf_ver: int | None = None
    license_text: str | None = None


@dataclass(frozen=True, slots=True)
class SdvxMetadata:
    song_id: int
    ascii_name: str
    entry: XmlElement
    assignments: tuple[ChartAssignment, ...]
    volume: int
    version: int
    root_attributes: tuple[tuple[str, str], ...] = ()

    @property
    def stem(self) -> str:
        return f"{self.song_id:04}_{self.ascii_name}"

    @property
    def directory(self) -> PurePosixPath:
        return PurePosixPath("music", self.stem)

    def chart_filename(self, slot: ChartSlot) -> str:
        return f"{self.stem}_{slot.suffix}.vox"

    def music_filename(self, *, preview: bool = False) -> str:
        return f"{self.stem}{'_pre' if preview else ''}.s3v"

    def jacket_filename(self, slot: ChartSlot, size: str = "standard") -> str:
        suffixes = {"standard": "", "small": "_s", "big": "_b"}
        if size not in suffixes:
            raise MetadataError(f"Unknown jacket size: {size}")
        return f"jk_{self.song_id:04}_{slot.number}{suffixes[size]}.png"
