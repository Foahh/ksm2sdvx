from dataclasses import replace

import pytest
from tests.conftest import document

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions, KsonChart, convert_chart, parse_kson
from ksm2sdvx.chart.errors import KsonDecodeError, KsonValidationError, UnsupportedFormatError
from ksm2sdvx.chart.kson.model import AutoTilt, ButtonNote, NoteInfo
from ksm2sdvx.chart.types import KsonDuration, KsonPulse


def test_defaults_and_compact_forms() -> None:
    chart = parse_kson(document(note={"bt": [[0, [240, 0], [480, 120]], (), (), ()]})).chart
    assert chart.note.bt[0][0].duration == 0
    assert chart.note.bt[0][1].duration == 0
    assert chart.beat.time_signatures[0].numerator == 4
    assert chart.beat.scroll_speed[0].incoming == 1.0


@pytest.mark.parametrize(
    "note", [False, True, 5.9, [5.9, 0], [0, -5], [-5, 0], [0, True], [0, 1, 2], "0"]
)
def test_invalid_button_forms(note: object) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(note={"bt": [[note], (), (), ()]}))


@pytest.mark.parametrize("notes", [[0, 0], [240, 0], [[0, 480], 240]])
def test_button_order_and_overlap(notes: object) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(note={"bt": [notes, (), (), ()]}))


@pytest.mark.parametrize(
    "note",
    [
        {"bt": [(), ()]},
        {"laser": [[[0, ()]], ()]},
        {"laser": [[[0, [[5, 0], [10, 1]]]], ()]},
        {"laser": [[[0, [[0, 0], [0, 1]]]], ()]},
        {"laser": [[[0, [[0, -0.1]]]], ()]},
        {"laser": [[[0, [[0, 0]], 3]], ()]},
        {"laser": [[[0, [[0, 0], [480, 1]]], [240, [[0, 0]]]], ()]},
    ],
)
def test_invalid_lasers_and_lanes(note: object) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(note=note))


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        document(meta={}),
        document(meta=None),
        document(beat={"bpm": ()}),
        document(beat={"bpm": [[0, 0]]}),
        document(beat={"bpm": [[240, 120]]}),
        document(beat={"bpm": [[0, float("nan")]]}),
        document(impl={"nested": None}),
    ],
)
def test_required_fields_nulls_and_numbers(text: str) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(text)


def test_decode_errors_version_and_bom() -> None:
    with pytest.raises(KsonDecodeError):
        parse_kson('{"format_version": 1, "format_version": 1}')
    with pytest.raises(KsonDecodeError):
        parse_kson("{")
    with pytest.raises(UnsupportedFormatError):
        parse_kson(document(format_version=2))
    parsed = parse_kson("\ufeff" + document())
    assert parsed.diagnostics[0].code == "UTF8_BOM"


def test_graph_and_tilt_unions() -> None:
    chart = parse_kson(
        document(
            camera={
                "cam": {"body": {"zoom_top": [[0, [1, 2], [0.3, 0.7]], [240, 0]]}},
                "tilt": [
                    [0, "normal"],
                    [120, 0.5],
                    [240, [0.5, 0.8]],
                    [360, [0.8, [0.3, 0.7]]],
                    [480, [[0.8, 1], [0.2, 0.6]]],
                    [600, [1, "bigger"]],
                ],
            }
        )
    ).chart
    assert chart.camera.zoom_top[0].outgoing == 2
    assert chart.camera.tilt[-1].outgoing == AutoTilt.BIGGER
    assert chart.camera.tilt[4].control.x == 0.2


@pytest.mark.parametrize(
    "tilt", [[[0, "unknown"]], [[0, 101]], [[0, [1, [2, 0]]]], [[0, [[1], [0, 0]]]]]
)
def test_invalid_tilt(tilt: object) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(camera={"tilt": tilt}))


def test_extensions_and_effects_are_retained() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120]], "custom": {"hello": "world"}},
            audio={
                "bgm": {"filename": "music.ogg", "offset": -120, "preview": {"offset": 30000}},
                "audio_effect": {
                    "fx": {
                        "def": [
                            ["second", {"type": "gate", "v": {"wave_length": "1/8"}}],
                            ["first", {"type": "retrigger"}],
                        ],
                        "param_change": {"second": {"wave_length": [[0, "1/16"]]}},
                        "long_event": {"second": [[0, [120, {"mix": "50%"}]], ()]},
                    }
                },
            },
        )
    ).chart
    assert chart.extensions[0].path == "/beat/custom"
    assert [d.name for d in chart.audio.fx.definitions] == ["second", "first"]
    assert chart.audio.fx.changes[0].value == "1/16"
    assert chart.audio.fx.invocations[1].parameters == (("mix", "50%"),)
    assert chart.audio.bgm is not None and chart.audio.bgm.offset == -120


def test_direct_models_are_validated(minimal_chart: KsonChart) -> None:
    notes = NoteInfo(bt=((ButtonNote(KsonPulse(0), KsonDuration(-5)),), (), (), ()))
    with pytest.raises(KsonValidationError):
        convert_chart(
            replace(minimal_chart, note=notes), options=ConversionOptions(), profile=DEFAULT_PROFILE
        )


@pytest.mark.parametrize(
    "audio",
    [
        {"key_sound": {"fx": {"chip_event": {"clap": ((False,), ())}}}},
        {"key_sound": {"fx": {"chip_event": {"clap": (((0, {"vol": -1}),), ())}}}},
        {"key_sound": {"laser": {"vol": ((240, 1), (0, 0.5))}}},
        {"audio_effect": {"laser": {"peaking_filter_delay": 161}}},
    ],
)
def test_invalid_retained_audio(audio: object) -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(audio=audio))


def test_invalid_optional_graph_and_swing() -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(camera={"cam": {"body": {"zoom_side": [[0, 0, [2, 0]]]}}}))
    with pytest.raises(KsonValidationError):
        parse_kson(
            document(
                camera={"cam": {"pattern": {"laser": {"slam_event": {"swing": [[0, 0, 240]]}}}}}
            )
        )
