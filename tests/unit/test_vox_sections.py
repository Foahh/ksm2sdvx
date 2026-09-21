from dataclasses import replace
from fractions import Fraction
from typing import cast

import pytest

from ksm2sdvx.chart import serialize_vox
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.model import (
    BpmOptions,
    CellDuration,
    ControllerName,
    ControllerSpan,
    LaserCurve,
    LaserMarker,
    ManualSpeed,
    MillisecondDuration,
    OpaqueController,
    OpaqueControllerName,
    OpaqueRow,
    PostEffect,
    PostEffectName,
    Realize,
    RollType,
    VoxBpmEvent,
    VoxBtNote,
    VoxChart,
    VoxLaserPoint,
    VoxMeterEvent,
    VoxPosition,
)
from ksm2sdvx.chart.vox.scripts import (
    ArithmeticOperator,
    Assignment,
    BinaryExpression,
    ComparisonOperator,
    Script,
    ScriptApplication,
    ScriptCondition,
    ScriptConstant,
    ScriptedTrack,
    ScriptNumber,
    ScriptVariable,
)
from ksm2sdvx.chart.vox.validation import Positions, roll_duration
from ksm2sdvx.common.types import Milliseconds

START = VoxPosition(1, 1, VoxTick(0))


def test_header_resolution_pause_and_bpm_options(vox_chart: VoxChart) -> None:
    text = serialize_vox(
        replace(
            vox_chart,
            beat_resolution=480,
            bpms=(
                VoxBpmEvent(START, 123.4567),
                VoxBpmEvent(VoxPosition(1, 2, VoxTick(12)), 123.4567, True),
            ),
            bpm_options=BpmOptions(True, 123.4567),
        )
    )
    assert text.startswith(
        "//====================================\n// SOUND VOLTEX OUTPUT TEXT FILE\n//====================================\n"
    )
    assert "#BEAT RESOLUTION\n480\n#END" in text
    assert "001,02,12\t123.4567\t4-" in text
    assert "#BPM OPTION\nConstantScroll\t1\nRepresentativeBpm\t123.4567\n#END" in text
    assert (
        text.index("#BEAT RESOLUTION")
        < text.index("#BEAT INFO")
        < text.index("#BPM INFO")
        < text.index("#BPM OPTION")
        < text.index("#TILT MODE INFO")
    )
    assert "\r" not in text


def test_resolution_and_simultaneous_meters(vox_chart: VoxChart) -> None:
    meters = (VoxMeterEvent(START, 4, 4), VoxMeterEvent(START, 3, 8))
    positions = Positions(meters, 480)
    assert positions.absolute(VoxPosition(2, 1, VoxTick(0))) == 720
    assert positions.absolute(VoxPosition(1, 3, VoxTick(239))) == 719
    target = replace(vox_chart, meters=meters, beat_resolution=480)
    assert "001,01,00\t4\t4\n001,01,00\t3\t8" in serialize_vox(target)
    with pytest.raises(ConversionError, match="outside"):
        positions.absolute(VoxPosition(1, 1, VoxTick(240)))


@pytest.mark.parametrize(
    ("kind", "beats"),
    [
        (RollType.ROLL, 7),
        (RollType.ROLL_TWO_BEATS, 2),
        (RollType.ROLL_THREE_BEATS, 3),
        (RollType.TRIPLE_ROLL, 12),
        (RollType.SWING, 3),
        (RollType.ROLL_TENTHS, 7),
        (RollType.SWING_TENTHS, 3),
    ],
)
def test_all_roll_types_and_default_lengths(
    vox_chart: VoxChart, kind: RollType, beats: int
) -> None:
    point = VoxLaserPoint(START, 0, LaserMarker.START, 1, roll_type=kind)
    assert roll_duration(point, 48) == beats * 48
    assert roll_duration(point, 480) == beats * 480
    end = replace(
        point,
        position=VoxPosition(1, 2, VoxTick(0)),
        value=1,
        marker=LaserMarker.END,
        roll_type=RollType.NONE,
    )
    tracks = tuple(
        replace(t, events=(point, end)) if t.number == 1 else t for t in vox_chart.tracks
    )
    text = serialize_vox(replace(vox_chart, tracks=tracks))
    assert f"001,01,00\t0.000000\t1\t{int(kind)}\t0\t1\t0\t0\t0\t0" in text


def test_v13_laser_columns_and_original_control_nodes(vox_chart: VoxChart) -> None:
    first = VoxLaserPoint(
        START, 0.123456, LaserMarker.START, 2, RollType.ROLL_TENTHS, 6, 0, LaserCurve.HERMITE, 2, 5
    )
    middle = replace(
        first,
        position=VoxPosition(1, 1, VoxTick(12)),
        marker=LaserMarker.CONTINUE,
        roll_type=RollType.NONE,
        roll_length=0,
    )
    last = replace(
        middle, position=VoxPosition(1, 2, VoxTick(0)), marker=LaserMarker.END, value=0.9
    )
    tracks = tuple(
        replace(t, events=(first, middle, last)) if t.number == 1 else t for t in vox_chart.tracks
    )
    text = serialize_vox(replace(vox_chart, tracks=tracks, original_left=(first, last)))
    assert "001,01,00\t0.123456\t1\t6\t6\t2\t0\t2\t2\t5" in text
    original = text.split("#TRACK ORIGINAL L\n")[1].split("#END")[0]
    assert len(original.splitlines()) == 2
    assert roll_duration(first, 48) == 24
    assert roll_duration(replace(first, roll_length=1), 48) == Fraction(24, 5)


def test_bt_unknown_column_and_optional_chain(vox_chart: VoxChart) -> None:
    note = VoxBtNote(START, VoxTick(48), 7, 24)
    tracks = tuple(replace(t, events=(note,)) if t.number == 3 else t for t in vox_chart.tracks)
    assert "#TRACK3\n001,01,00\t48\t7\t24" in serialize_vox(replace(vox_chart, tracks=tracks))


def test_unordered_controllers_and_unknown_fields_are_preserved(vox_chart: VoxChart) -> None:
    late = ControllerSpan(
        VoxPosition(2, 1, VoxTick(0)), ControllerName.MORPHING_2, VoxTick(48), 0, -2.82
    )
    early = Realize(START, 3, 17.12, 60.12, 110.12)
    raw = OpaqueController(
        START, OpaqueControllerName.SPECIAL, (0, 0, "LANECLEARCOL", "x80202020", 0, 0)
    )
    locked = ManualSpeed(START, 1.0)
    target = replace(vox_chart, controllers=(late, early, raw), locked_controllers=(locked,))
    text = serialize_vox(target)
    assert text.index("\tMorphing2") < text.index("\tRealize") < text.index("\tSpecialN")
    assert "Realize\t3\t0\t17.12\t60.12\t110.12\t0.00" in text
    assert "#LOCKED_SPCONTROLER\n001,01,00\tManualSpeed\t0\t0\tf1.00\t0.00\t0.00\t0.00" in text


def test_post_effect_duration_units_and_unknown_sections(vox_chart: VoxChart) -> None:
    cell = PostEffect(
        START, CellDuration(VoxTick(24)), PostEffectName.CHROMATIC_ABERRATION, "Strength", 0.0, 0.02
    )
    millis = replace(
        cell,
        duration=MillisecondDuration(Milliseconds(125)),
        name=PostEffectName.CRT_MONITOR,
        parameter="Active",
        end_value=1.0,
    )
    text = serialize_vox(
        replace(
            vox_chart,
            post_effects=(cell, millis),
            lyrics=(OpaqueRow(("entry", 2)),),
            reverb=(OpaqueRow(("uninterpreted", "0.0")),),
        )
    )
    assert "001,01,00\t2\t24\tChromaticAbberation\t0\t0\tStrength\t0.0f\t0.02f" in text
    assert "001,01,00\t2\t125ms\tCrtMonitorEffect\t0\t0\tActive\t0.0f\t1.0f" in text
    assert "#LYRIC INFO\nentry\t2" in text
    assert "#REVERB EFFECT PARAM\nuninterpreted\t0.0" in text


def test_scripts_and_application_order(vox_chart: VoxChart) -> None:
    condition = ScriptCondition(
        ScriptConstant.CURRENT_STEP, ComparisonOperator.LESS_EQUAL, ScriptNumber(48)
    )
    expression = BinaryExpression(
        ScriptVariable.TARGET_STEP, ArithmeticOperator.ADD, ScriptNumber(24)
    )
    scripts = (
        Script(10, (Assignment(ScriptVariable.TARGET_STEP, expression, condition),)),
        Script(20, (Assignment(ScriptVariable.OFFSET_X, ScriptNumber(-0.178, True)),)),
    )
    tracks = (ScriptedTrack(3, (ScriptApplication(START, (20, 10)),)),)
    text = serialize_vox(replace(vox_chart, scripts=scripts, scripted_tracks=tracks))
    assert "$targetStep = ( $targetStep + 24 ) when $currentStep <= 48" in text
    assert "$offsetX = -0.178f" in text
    assert "#SCRIPTED_TRACK3\n001,01,00 20 10\n#END" in text
    assert text.index("@SCRIPTSTART 10") < text.index("@SCRIPTSTART 20")


def test_reject_invalid_scripts(vox_chart: VoxChart) -> None:
    script = Script(10, (Assignment(ScriptVariable.OFFSET_Y, ScriptNumber(0.12345)),))
    with pytest.raises(ConversionError, match="three decimal"):
        serialize_vox(replace(vox_chart, scripts=(script,)))
    with pytest.raises(ConversionError, match="missing script"):
        serialize_vox(
            replace(
                vox_chart, scripted_tracks=(ScriptedTrack(3, (ScriptApplication(START, (9,)),)),)
            )
        )
    valid = Script(10, ())
    with pytest.raises(ConversionError, match="Duplicate"):
        serialize_vox(replace(vox_chart, scripts=(valid, valid)))
    invalid = Script(
        10, (Assignment(cast(ScriptVariable, ScriptConstant.CURRENT_STEP), ScriptNumber(1)),)
    )
    with pytest.raises(ConversionError, match="assignment target"):
        serialize_vox(replace(vox_chart, scripts=(invalid,)))


@pytest.mark.parametrize("payload", ["x\n#END", "a\tb", "//hidden", "\x00"])
def test_opaque_payload_cannot_inject_rows(vox_chart: VoxChart, payload: str) -> None:
    with pytest.raises(ConversionError, match="fields"):
        serialize_vox(replace(vox_chart, lyrics=(OpaqueRow((payload,)),)))
