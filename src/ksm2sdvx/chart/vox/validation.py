"""Validate VOX v13 structure without imposing converter-specific conventions."""

from bisect import bisect_right
from fractions import Fraction

from ksm2sdvx.chart.errors import ConversionError, UnsupportedFormatError
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.effects import FX_INTEGER_COLUMNS, effect_columns
from ksm2sdvx.chart.vox.model import (
    AirScale,
    CellDuration,
    Controller,
    ControllerName,
    ControllerSpan,
    LaserCurve,
    LaserMarker,
    ManualSpeed,
    MillisecondDuration,
    OpaqueController,
    OpaqueControllerName,
    PostEffectName,
    Realize,
    RollType,
    TiltMode,
    TiltNode,
    VoxBtNote,
    VoxChart,
    VoxFxChip,
    VoxFxHold,
    VoxLaserPoint,
    VoxMeterEvent,
    VoxPosition,
)
from ksm2sdvx.chart.vox.scripts import script_lines
from ksm2sdvx.chart.vox.values import field, finite, integer, text_field


def validate_position(position: VoxPosition) -> None:
    integer(position.measure, 1)
    integer(position.beat, 1)
    integer(position.tick)


class Positions:
    """Map positions using chart resolution; the last simultaneous meter wins."""

    def __init__(self, meters: tuple[VoxMeterEvent, ...], resolution: int = 48) -> None:
        self.whole = integer(resolution, 1) * 4
        if not meters or meters[0].position != VoxPosition(1, 1, VoxTick(0)):
            raise ConversionError("VOX requires an initial meter")
        starts: list[Fraction] = []
        for i, event in enumerate(meters):
            validate_position(event.position)
            integer(event.numerator, 1)
            integer(event.denominator, 1)
            if event.position.beat != 1 or event.position.tick != 0:
                raise ConversionError("Meter changes must begin a measure")
            if i == 0:
                starts.append(Fraction(0))
            else:
                previous = meters[i - 1]
                delta = event.position.measure - previous.position.measure
                if delta < 0:
                    raise ConversionError("Meter changes must be ordered")
                starts.append(
                    starts[-1]
                    + delta * Fraction(self.whole * previous.numerator, previous.denominator)
                )
            if starts[-1].denominator != 1:
                raise ConversionError("Meter change falls between VOX ticks")
        self.meters = meters
        self.measures = tuple(e.position.measure for e in meters)
        self.starts = tuple(starts)

    def absolute(self, position: VoxPosition) -> Fraction:
        validate_position(position)
        i = bisect_right(self.measures, position.measure) - 1
        meter = self.meters[i]
        beat_length = Fraction(self.whole, meter.denominator)
        if position.beat > meter.numerator or position.tick >= beat_length:
            raise ConversionError(f"Position lies outside its meter: {position}")
        beats = (position.measure - meter.position.measure) * meter.numerator + position.beat - 1
        absolute = self.starts[i] + beats * beat_length + position.tick
        if absolute.denominator != 1:
            raise ConversionError("Position falls between VOX ticks")
        return absolute


def roll_duration(event: VoxLaserPoint, resolution: int) -> Fraction:
    """C9 is in quarter notes (types 1..5) or tenths (6/7), not cells."""
    if type(event.roll_type) is not RollType:
        raise ConversionError("Invalid VOX roll type")
    length = integer(event.roll_length)
    if event.roll_type == RollType.NONE:
        if length:
            raise ConversionError("A roll length requires a roll type")
        return Fraction(0)
    if not length:
        defaults = (0, 7, 2, 3, 12, 3, 7, 3)
        return Fraction(defaults[event.roll_type] * resolution)
    return Fraction(length * resolution, 10 if event.roll_type in (6, 7) else 1)


def validate_effects(chart: VoxChart) -> None:
    if len(chart.laser_effects) != 5:
        raise ConversionError("TAB EFFECT INFO requires five entries")
    if len(chart.fx_effects) != 12:
        raise ConversionError("FXBUTTON EFFECT INFO requires twelve pairs")
    if len(chart.parameter_assignments) != 24:
        raise ConversionError("TAB PARAM ASSIGN INFO requires twenty-four entries")
    for effect in chart.laser_effects:
        columns = effect_columns(effect)
        for i, value in enumerate(columns[1:], 1):
            if effect.kind == 3 and i == 2:
                integer(value)
            else:
                finite(value)
    for pair in chart.fx_effects:
        for effect in (pair.first, pair.second):
            for i, value in enumerate(effect_columns(effect)[1:], 1):
                if i in FX_INTEGER_COLUMNS[effect.kind]:
                    integer(value, None)
                else:
                    finite(value)
    for i, assignment in enumerate(chart.parameter_assignments):
        if integer(assignment.pair_index) != i // 2:
            raise ConversionError("Parameter assignment pair indices must be 0,0,..,11,11")
        parameter = integer(assignment.parameter)
        pair = chart.fx_effects[i // 2]
        effect = pair.first if i % 2 == 0 else pair.second
        if parameter >= len(effect_columns(effect)):
            raise ConversionError("Assigned parameter does not exist in its effect row")
        finite(assignment.from_value)
        finite(assignment.to_value)  # Descending sweeps are valid.


def validate_lasers(
    events: tuple[VoxLaserPoint, ...], positions: Positions, end: Fraction, resolution: int
) -> None:
    active = False
    previous = Fraction(-1)
    for event in events:
        absolute = positions.absolute(event.position)
        if absolute < previous or absolute > end:
            raise ConversionError("Invalid laser event order or end position")
        previous = absolute
        finite(event.value)
        if not 0 <= event.value <= 1 or integer(event.width) not in (1, 2):
            raise ConversionError("Invalid laser position or width")
        if integer(event.effect) not in range(7):
            raise ConversionError("Invalid laser effect selector")
        if integer(event.unused_c6) != 0:
            raise ConversionError("Laser C6 is unused and must be zero")
        integer(event.unknown_c8, None)
        if type(event.curve_type) is not LaserCurve or type(event.marker) is not LaserMarker:
            raise ConversionError("Invalid laser curve or node type")
        if event.marker == LaserMarker.START:
            if active:
                raise ConversionError("Laser sections overlap")
            active = True
        elif not active:
            raise ConversionError("Laser point precedes section start")
        if event.marker == LaserMarker.END:
            active = False
        if absolute + roll_duration(event, resolution) > end:
            raise ConversionError("Roll duration exceeds end position")
    if active:
        raise ConversionError("Unclosed laser section")


def validate_controllers(
    events: tuple[Controller, ...], positions: Positions, end: Fraction
) -> None:
    # SPCONTROLER and LOCKED_SPCONTROLER need not be in time order.
    for event in events:
        absolute = positions.absolute(event.position)
        if absolute > end:
            raise ConversionError("Controller exceeds end position")
        if isinstance(event, Realize):
            integer(event.controller, None)
            for value in (event.c3, event.c4, event.c5, event.c6, event.c7):
                finite(value)
        elif isinstance(event, AirScale):
            if type(event.right) is not bool:
                raise ConversionError("Invalid air scale side")
            integer(event.c2, None)
            for value in (event.c3, event.c4, event.c5, event.c6, event.c7):
                finite(value)
        elif isinstance(event, ControllerSpan):
            finite(event.start_value)
            finite(event.end_value)
            integer(event.start_mode, None)
            finite(event.unused_c7)
            if type(event.name) is not ControllerName or type(event.node_type) is not TiltNode:
                raise ConversionError("Invalid controller span")
            if event.name != ControllerName.TILT and event.node_type != TiltNode.CONTINUE:
                raise ConversionError("Only Tilt has a node type")
            if event.name in (ControllerName.ROTATION_Z, ControllerName.MORPHING_2) and any(
                abs(value) > float.fromhex("0x1.fffffep+127")
                for value in (
                    event.start_value,
                    event.end_value,
                    event.end_value - event.start_value,
                )
            ):
                raise ConversionError(f"{event.name.value} span exceeds the float32 range")
            if absolute + integer(event.duration) > end:
                raise ConversionError("Controller duration exceeds end position")
        elif isinstance(event, ManualSpeed):
            finite(event.multiplier)
            if abs(event.multiplier) > float.fromhex("0x1.fffffep+127"):
                raise ConversionError("ManualSpeed multiplier exceeds the float32 range")
            if integer(event.unknown_c2) > 0xFFFFFFFF:
                raise ConversionError("ManualSpeed C2 must fit an unsigned 32-bit integer")
        elif type(event) is OpaqueController:
            if type(event.name) is not OpaqueControllerName:
                raise ConversionError("Invalid opaque controller name")
            for value in event.fields:
                field(value)
            if event.name == OpaqueControllerName.BAR_OFF and (
                len(event.fields) < 3 or event.fields[2] not in ("ON", "OFF")
            ):
                raise ConversionError("BAROFF C4 must be ON or OFF")


def validate_vox(chart: VoxChart) -> None:
    if type(chart.format_version) is not int or chart.format_version != 13:
        raise UnsupportedFormatError(f"Unsupported VOX version: {chart.format_version}")
    if tuple(integer(t.number, 1) for t in chart.tracks) != tuple(range(1, 9)):
        raise ConversionError("VOX requires eight ordered tracks")
    positions = Positions(chart.meters, chart.resolution)
    end = positions.absolute(chart.end_position)
    validate_effects(chart)
    if not chart.bpms or chart.bpms[0].position != VoxPosition(1, 1, VoxTick(0)):
        raise ConversionError("VOX requires an initial BPM")
    for rows in (chart.bpms, chart.meters, chart.tilt_modes, chart.auto_tab):
        previous = Fraction(-1)
        for event in rows:
            absolute = positions.absolute(event.position)
            if absolute < previous or absolute > end:
                raise ConversionError("VOX events must be ordered and within the end position")
            previous = absolute
    for event in chart.bpms:
        finite(event.bpm)
        if event.bpm <= 0 or type(event.pause) is not bool:
            raise ConversionError("Invalid VOX BPM or pause flag")
    if chart.bpm_options is not None:
        finite(chart.bpm_options.representative_bpm)
        if (
            chart.bpm_options.representative_bpm <= 0
            or type(chart.bpm_options.constant_scroll) is not bool
        ):
            raise ConversionError("Invalid BPM OPTION")
    for mode in chart.tilt_modes:
        if type(mode.mode) is not TiltMode:
            raise ConversionError("Unsupported VOX tilt mode")
    for track in chart.tracks:
        if track.number in (1, 8):
            lasers = tuple(e for e in track.events if isinstance(e, VoxLaserPoint))
            if len(lasers) != len(track.events):
                raise ConversionError("Laser track contains a button")
            validate_lasers(lasers, positions, end, chart.resolution)
            continue
        previous_end = previous_start = Fraction(-1)
        for note in track.events:
            absolute = positions.absolute(note.position)
            if isinstance(note, VoxBtNote):
                if track.number not in (3, 4, 5, 6):
                    raise ConversionError("BT note must be in a BT track")
                integer(note.unknown_c2, None)
                duration = integer(note.duration)
            elif isinstance(note, (VoxFxChip, VoxFxHold)):
                if track.number not in (2, 7):
                    raise ConversionError("FX note must be in an FX track")
                if isinstance(note, VoxFxChip):
                    if integer(note.sample) not in (*range(15), 255):
                        raise ConversionError("Unknown FX chip sample")
                    duration = 0
                else:
                    duration = integer(note.duration, 1)
                    if integer(note.effect_pair) not in range(2, 14):
                        raise ConversionError("FX hold pair must use a 2-indexed reference")
            else:
                raise ConversionError("Button track contains a laser")
            if note.cells_per_chain is not None:
                integer(note.cells_per_chain, 1)
            if absolute < previous_end or absolute == previous_start:
                raise ConversionError("VOX buttons overlap or are out of order")
            if absolute + duration > end:
                raise ConversionError("Button duration exceeds end position")
            previous_end, previous_start = absolute + duration, absolute
    # Original tracks are independent control nodes, not copies of expanded samples.
    for original in (chart.original_left, chart.original_right):
        validate_lasers(original, positions, end, chart.resolution)
    for auto in chart.auto_tab:
        if integer(auto.effect_pair) not in range(2, 14):
            raise ConversionError("AUTO TAB pair must use a 2-indexed reference")
        if positions.absolute(auto.position) + integer(auto.duration) > end:
            raise ConversionError("AUTO TAB duration exceeds end position")
    validate_controllers(chart.controllers, positions, end)
    validate_controllers(chart.locked_controllers or (), positions, end)
    for row in (*chart.lyrics, *chart.reverb):
        if not row.fields:
            raise ConversionError("An opaque row must contain fields")
        for value in row.fields:
            field(value)
    for post in chart.post_effects or ():
        if positions.absolute(post.position) > end:
            raise ConversionError("Post-effect exceeds end position")
        if type(post.name) is not PostEffectName:
            raise ConversionError("Invalid post-effect name")
        if type(post.duration) not in (CellDuration, MillisecondDuration):
            raise ConversionError("Invalid post-effect duration unit")
        integer(post.duration.value)
        if isinstance(post.duration, CellDuration) and (
            positions.absolute(post.position) + post.duration.value > end
        ):
            raise ConversionError("Post-effect duration exceeds end position")
        for value in (post.unknown_c1, post.unknown_c4, post.unknown_c5):
            integer(value, None)
        text_field(post.parameter)
        finite(post.start_value)
        finite(post.end_value)
    identifiers: set[int] = set()
    for script in chart.scripts or ():
        script_lines(script)
        if script.identifier in identifiers:
            raise ConversionError("Duplicate script identifier")
        identifiers.add(script.identifier)
    track_numbers: set[int] = set()
    for track in chart.scripted_tracks:
        if integer(track.number) not in range(1, 9) or track.number in track_numbers:
            raise ConversionError("Invalid or duplicate scripted track")
        track_numbers.add(track.number)
        for application in track.applications:
            if positions.absolute(application.position) > end or not application.script_ids:
                raise ConversionError("Invalid script application")
            for identifier in application.script_ids:
                if integer(identifier) not in identifiers:
                    raise ConversionError("Script application references a missing script")
