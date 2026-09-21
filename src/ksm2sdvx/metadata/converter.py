"""Convert per-chart metadata into one explicitly assigned SDVX database entry."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.metadata.database import XmlElement, from_element, to_element
from ksm2sdvx.metadata.errors import MetadataError
from ksm2sdvx.metadata.models import (
    MAX_SONG_ID,
    ChartAssignment,
    ChartMetadata,
    ChartRadar,
    ChartSlot,
    MetadataResult,
    PackageMetadata,
    SdvxMetadata,
    SdvxMetadataSettings,
)


def _integer(value: int, *, name: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum:
        raise MetadataError(f"{name} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise MetadataError(f"{name} must be at most {maximum}")
    return value


def _add(parent: ET.Element[str], name: str, value: str | int, kind: str = "") -> None:
    ET.SubElement(parent, name, {"__type": kind} if kind else {}).text = str(value)


def _shared(values: tuple[str, ...], override: str | None, name: str) -> str:
    if override is not None:
        result = override
    elif len(set(values)) != 1:
        raise MetadataError(f"Charts have different {name} values; supply an explicit {name}")
    else:
        result = values[0]
    if not result.strip():
        raise MetadataError(f"{name} must not be empty")
    return result


def _bpm(value: float | str) -> int:
    try:
        number = Decimal(str(value)) * 100
    except InvalidOperation as exc:
        raise MetadataError("BPM values must be finite numbers") from exc
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        raise MetadataError("Database BPM must be positive and have at most two decimal places")
    return _integer(int(number), name="BPM hundredths", minimum=1, maximum=2**32 - 1)


def _bpm_range(source: PackageMetadata, settings: SdvxMetadataSettings) -> tuple[int, int]:
    if settings.bpm_min is not None and settings.bpm_max is not None:
        low, high = _bpm(settings.bpm_min), _bpm(settings.bpm_max)
    elif settings.bpm_min is not None or settings.bpm_max is not None:
        raise MetadataError("Set both bpm_min and bpm_max")
    else:
        displays = {chart.display_bpm for chart in source.charts}
        if len(displays) != 1 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", next(iter(displays))):
            raise MetadataError("Supply bpm_min and bpm_max for variable or differing display BPM")
        low = high = _bpm(next(iter(displays)))
    if low > high:
        raise MetadataError("bpm_min must not exceed bpm_max")
    return low, high


def _diagnostic(code: str, message: str) -> Diagnostic:
    return Diagnostic(code, Severity.WARNING, Stage.METADATA, message, "metadata")


def _jacket_author(source: ChartMetadata, assignment: ChartAssignment) -> str:
    if assignment.jacket_author is not None:
        return assignment.jacket_author
    for field in source.retained:
        if field.json_pointer == "/meta/jacket_author" and isinstance(field.value, str):
            return field.value
    return ""


def _chart_entry(
    slot: ChartSlot,
    source: ChartMetadata | None = None,
    assignment: ChartAssignment | None = None,
) -> ET.Element[str]:
    chart = ET.Element(slot.value)
    level, score, price, limited = 0, 0, -1, 3
    author, jacket_author = "", ""
    if source is not None and assignment is not None:
        level = (
            assignment.level_tenths if assignment.level_tenths is not None else source.level * 10
        )
        level = _integer(level, name="level_tenths", minimum=1, maximum=255)
        author, jacket_author = source.chart_author, _jacket_author(source, assignment)
        score = _integer(
            assignment.max_exscore if assignment.max_exscore is not None else 0,
            name="max_exscore",
            minimum=0,
            maximum=2**31 - 1,
        )
        price = _integer(
            assignment.price if assignment.price is not None else -1,
            name="price",
            minimum=-(2**31),
            maximum=2**31 - 1,
        )
        limited = _integer(
            assignment.limited if assignment.limited is not None else 3,
            name="limited",
            minimum=0,
            maximum=255,
        )
    _add(chart, "difnum", level, "u8")
    _add(chart, "illustrator", jacket_author)
    _add(chart, "effected_by", author)
    _add(chart, "price", price, "s32")
    _add(chart, "limited", limited, "u8")
    _add(
        chart,
        "jacket_print",
        _integer(
            assignment.jacket_print if assignment is not None else -2,
            name="jacket_print",
            minimum=-(2**31),
            maximum=2**31 - 1,
        ),
        "s32",
    )
    _add(
        chart,
        "jacket_mask",
        _integer(
            assignment.jacket_mask if assignment is not None else 0,
            name="jacket_mask",
            minimum=-(2**31),
            maximum=2**31 - 1,
        ),
        "s32",
    )
    _add(chart, "max_exscore", score, "s32")
    radar = ET.SubElement(chart, "radar")
    values = assignment.radar if assignment is not None else ChartRadar()
    for name, value in values.items():
        _add(
            radar,
            name,
            _integer(
                value if value is not None else 0,
                name=f"radar.{name}",
                minimum=0,
                maximum=65535,
            ),
            "u16",
        )
    return chart


class SdvxMetadataConverter:
    def convert(
        self, source: PackageMetadata, *, settings: SdvxMetadataSettings
    ) -> MetadataResult[SdvxMetadata]:
        """Build a new entry from source metadata and explicit target defaults."""
        _integer(settings.song_id, name="song_id", minimum=1, maximum=MAX_SONG_ID)
        if settings.song_id in settings.database.song_ids:
            raise MetadataError(f"Song ID {settings.song_id} already exists in the music database")
        if not source.charts or not settings.charts:
            raise MetadataError("At least one chart and slot assignment are required")
        sources = {chart.source: chart for chart in source.charts}
        if len(sources) != len(source.charts):
            raise MetadataError("Source chart metadata contains duplicate paths")
        assigned_sources = {assignment.source for assignment in settings.charts}
        assigned_slots = {assignment.slot for assignment in settings.charts}
        if len(assigned_sources) != len(settings.charts) or len(assigned_slots) != len(
            settings.charts
        ):
            raise MetadataError("Every source chart and target slot must be assigned exactly once")
        if assigned_sources != sources.keys():
            raise MetadataError("Slot assignments must cover exactly the supplied source charts")
        if any(type(assignment.slot) is not ChartSlot for assignment in settings.charts):
            raise MetadataError("Chart assignments must use valid ChartSlot values")
        if settings.ascii_name is None or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]*", settings.ascii_name
        ):
            raise MetadataError(
                "ascii_name must contain only ASCII letters, digits, underscores or hyphens"
            )
        title = _shared(tuple(chart.title for chart in source.charts), settings.title, "title")
        artist = _shared(tuple(chart.artist for chart in source.charts), settings.artist, "artist")
        minimum_bpm, maximum_bpm = _bpm_range(source, settings)
        entry = ET.Element("music", {"id": str(settings.song_id)})
        info = ET.SubElement(entry, "info")
        _add(info, "title_name", title)
        _add(
            info,
            "title_yomigana",
            title if settings.title_yomigana is None else settings.title_yomigana,
        )
        _add(info, "artist_name", artist)
        _add(
            info,
            "artist_yomigana",
            artist if settings.artist_yomigana is None else settings.artist_yomigana,
        )
        _add(info, "ascii", settings.ascii_name)
        _add(info, "bpm_max", maximum_bpm, "u32")
        _add(info, "bpm_min", minimum_bpm, "u32")
        if type(settings.distribution_date) is not date or settings.distribution_date.year < 1000:
            raise MetadataError("distribution_date must be a date with a four-digit year")
        _add(info, "distribution_date", int(settings.distribution_date.strftime("%Y%m%d")), "u32")
        volume = _integer(settings.volume, name="volume", minimum=0, maximum=65535)
        version = _integer(settings.version, name="version", minimum=1, maximum=255)
        _add(info, "volume", volume, "u16")
        _add(info, "bg_no", _integer(settings.bg_no, name="bg_no", minimum=0, maximum=65535), "u16")
        _add(
            info,
            "genre",
            _integer(settings.genre, name="genre", minimum=0, maximum=2**32 - 1),
            "u32",
        )
        _add(
            info,
            "is_fixed",
            _integer(settings.is_fixed, name="is_fixed", minimum=0, maximum=255),
            "u8",
        )
        _add(info, "version", version, "u8")
        _add(
            info,
            "demo_pri",
            _integer(settings.demo_pri, name="demo_pri", minimum=-128, maximum=127),
            "s8",
        )
        inf_ver = (
            settings.inf_ver
            if settings.inf_ver is not None
            else (2 if ChartSlot.INFINITE in assigned_slots else 0)
        )
        _add(info, "inf_ver", _integer(inf_ver, name="inf_ver", minimum=0, maximum=255), "u8")
        if settings.license_text is not None:
            _add(info, "license_text", settings.license_text)
        difficulty = ET.SubElement(entry, "difficulty")
        selected = {assignment.slot: assignment for assignment in settings.charts}
        for slot in ChartSlot:
            assignment = selected.get(slot)
            if assignment is not None:
                difficulty.append(_chart_entry(slot, sources[assignment.source], assignment))
            else:
                difficulty.append(_chart_entry(slot))
        metadata = SdvxMetadata(
            settings.song_id,
            settings.ascii_name,
            from_element(entry),
            settings.charts,
            volume,
            version,
            settings.database.attributes,
        )
        # Verify encoding while conversion errors still have their metadata context.
        serialize_music_database(metadata)
        diagnostics: list[Diagnostic] = []
        if any(not assignment.radar.complete for assignment in settings.charts):
            diagnostics.append(
                _diagnostic(
                    "RADAR_NOT_COMPUTED",
                    "Unspecified radar values are set to zero; chart radar analysis is not implemented.",
                )
            )
        if any(assignment.max_exscore is None for assignment in settings.charts):
            diagnostics.append(
                _diagnostic(
                    "MAX_EXSCORE_NOT_COMPUTED",
                    "Unspecified max_exscore values are set to zero; provide explicit values when needed.",
                )
            )
        return MetadataResult(metadata, tuple(diagnostics))


def serialize_music_database(metadata: SdvxMetadata) -> bytes:
    """Serialize one new entry for others/music_db.merged.xml in Windows Shift-JIS."""
    root = to_element(XmlElement("mdb", metadata.root_attributes, children=(metadata.entry,)))
    ET.indent(root, space="  ")
    text = (
        '<?xml version="1.0" encoding="shift-jis"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )
    try:
        encoded = text.encode("cp932")
        # ElementTree accepts control characters when serializing; parsing catches invalid XML.
        ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise MetadataError(
            f"Metadata must be valid XML text representable in Shift-JIS: {exc}"
        ) from exc
    return encoded
