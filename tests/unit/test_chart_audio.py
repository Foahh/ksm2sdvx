from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.conftest import document

from ksm2sdvx.chart import (
    DEFAULT_PROFILE,
    ConversionOptions,
    apply_rendered_audio,
    compile_chart_audio,
    convert_chart,
    parse_kson,
)
from ksm2sdvx.chart.audio_timing import AudioClock
from ksm2sdvx.chart.conversion.converter import UnsupportedFeaturesError
from ksm2sdvx.chart.errors import ConversionError, KsonValidationError
from ksm2sdvx.chart.kson.model import ChipKeySound, KeySoundInfo
from ksm2sdvx.chart.types import KsonPulse
from ksm2sdvx.chart.vox.model import VoxFxChip, VoxLaserPoint
from ksm2sdvx.common.diagnostics import FeatureStatus


def test_typed_keysounds_and_laser_audio_parameters() -> None:
    chart = parse_kson(
        document(
            audio={
                "key_sound": {
                    "fx": {
                        "chip_event": {
                            "clap": [[0, [240, {"vol": 0.4}]], []],
                            "hit.wav": [[], [120]],
                        }
                    }
                },
                "audio_effect": {
                    "laser": {
                        "peaking_filter_delay": 80,
                        "legacy": {"filter_gain": [[0, 0.5], [240, 0.75]]},
                    }
                },
            }
        )
    ).chart
    assert [
        (c.pulse, c.lane, c.sample, c.volume, c.preset) for c in chart.audio.key_sound.chips
    ] == [(0, 0, "clap", 1.0, True), (240, 0, "clap", 0.4, True), (120, 1, "hit.wav", 1.0, False)]
    assert chart.audio.laser.peaking_filter_delay == 80
    assert [e.value for e in chart.audio.laser.filter_gain] == [0.5, 0.75]


def test_audio_accepts_source_pulses_outside_vox_grid_and_preserves_tempo() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120], [240, 240]]},
            note={"fx": [[1, 480], []]},
            audio={"bgm": {"offset": -125, "vol": 0.7}},
        )
    ).chart
    program = compile_chart_audio(chart)
    clock = AudioClock(chart, 44100)
    assert clock.frame(240) == 22050
    assert clock.frame(480) == 33075
    assert program.offset_frames == -5512
    assert program.bgm_volume == 0.7
    assert program.tempos[1].pulse == 240
    with pytest.raises(ConversionError):
        convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)


def test_mid_hold_changes_and_separate_lane_precedence_data() -> None:
    chart = parse_kson(
        document(
            note={"fx": [[[0, 480], [720, 240]], [[120, 240]]]},
            audio={
                "audio_effect": {
                    "fx": {
                        "long_event": {
                            "retrigger": [
                                [[0, {"wave_length": "1/8"}], 500],
                                [[120, {"wave_length": "1/16"}]],
                            ],
                            "gate": [[240], []],
                            "": [[360], []],
                        }
                    }
                }
            },
        )
    ).chart
    program = compile_chart_audio(chart)
    assert [
        (e.effect, e.lane, e.start_frame, e.end_frame, e.hold_start_frame) for e in program.fx
    ] == [
        ("retrigger", 0, 0, 22050, 0),
        ("retrigger", 1, 11025, 33075, 11025),
        ("gate", 0, 22050, 33075, 0),
    ]
    assert len(program.fx_holds) == 3
    assert [d.pulse for d in program.diagnostics if d.code == "IGNORED_FX_EVENT"] == [500]


def test_definition_order_and_inactive_parameter_values_are_preserved() -> None:
    chart = parse_kson(
        document(
            audio={
                "audio_effect": {
                    "laser": {
                        "def": [
                            ["B", {"type": "gate", "v": {"mix": "90%"}}],
                            ["A", {"type": "retrigger", "v": {"mix": "0%>90%"}}],
                        ],
                        "param_change": {"B": {"mix": [[120, "50%>100%"]]}},
                    }
                }
            }
        )
    ).chart
    program = compile_chart_audio(chart)
    custom = [e for e in program.effects if not e.builtin]
    assert [(e.name, e.parameters) for e in custom] == [
        ("B", (("mix", "90%"),)),
        ("A", (("mix", "0%>90%"),)),
    ]
    assert program.changes[0].value == "50%>100%"
    assert program.laser_events[0].effect == "peaking_filter"


def test_laser_jumps_wide_coordinates_and_bpm_crossing_keep_source_graph() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120], [240, 240]]},
            note={"laser": [[[0, [[0, 0, [0.25, 0.75]], [480, [0.25, 1]], [720, 0]], 2]], []]},
        )
    ).chart
    laser = compile_chart_audio(chart).lasers[0]
    assert laser.points[0].curve_x == 0.25
    assert laser.points[0].curve_y == 0.75
    assert (
        laser.points[1].pulse,
        laser.points[1].frame,
        laser.points[1].incoming,
        laser.points[1].outgoing,
    ) == (480, 33075, 0.25, 1)
    assert laser.end_frame == 44100


def test_keysound_resources_ignore_events_without_chips() -> None:
    chart = parse_kson(
        document(
            note={"fx": [[0, [240, 240]], [120]]},
            audio={
                "key_sound": {
                    "fx": {
                        "chip_event": {
                            "clap": [[0, 240, 720], []],
                            "hit.wav": [[], [[120, {"vol": 0.5}]]],
                        }
                    }
                }
            },
        )
    ).chart
    program = compile_chart_audio(chart)
    assert [(k.resource_id, k.volume) for k in program.keysounds] == [("clap", 1), ("hit.wav", 0.5)]
    assert [(r.name, r.preset) for r in program.resources] == [("clap", True), ("hit.wav", False)]
    assert len([d for d in program.diagnostics if d.code == "IGNORED_CHIP_KEYSOUND"]) == 2


def test_switch_audio_resources_and_invocations() -> None:
    chart = parse_kson(
        document(
            note={"fx": [[[0, 480]], []]},
            audio={
                "audio_effect": {
                    "fx": {
                        "def": [
                            ["alternate", {"type": "switch_audio", "v": {"filename": "one.ogg"}}],
                            ["second", {"type": "switch_audio", "v": {"filename": "two.ogg"}}],
                        ],
                        "long_event": {"alternate": [[0], []], "second": [[240], []]},
                    }
                }
            },
        )
    ).chart
    program = compile_chart_audio(chart)
    assert {r.name for r in program.resources} == {"one.ogg", "two.ogg"}
    assert program.fx[0].effect == "alternate"
    assert program.fx[1].effect == "second"


@pytest.mark.parametrize(
    "event",
    [
        {"param_change": {"alternate": {"filename": [[240, "two.ogg"]]}}},
        {"long_event": {"alternate": [[[0, {"filename": "two.ogg"}]], []]}},
    ],
)
def test_filename_parameters_cannot_change_after_definition(event: dict[str, object]) -> None:
    with pytest.raises(KsonValidationError, match="only be set in effect definitions"):
        parse_kson(
            document(
                audio={
                    "audio_effect": {
                        "fx": {
                            "def": [
                                [
                                    "alternate",
                                    {"type": "switch_audio", "v": {"filename": "one.ogg"}},
                                ]
                            ],
                            **event,
                        }
                    }
                }
            )
        )


def test_triggers_reset_inside_non_four_four_measures() -> None:
    chart = parse_kson(
        document(
            beat={"bpm": [[0, 120]], "time_sig": [[0, [3, 4]], [1, [5, 4]]]},
            note={"fx": [[[0, 1920]], []]},
            audio={
                "audio_effect": {
                    "fx": {"def": [["R", {"type": "retrigger", "v": {"update_period": "1/2"}}]]}
                }
            },
        )
    ).chart
    program = compile_chart_audio(chart)
    effect = next(e for e in program.effects if e.name == "R")
    clock = AudioClock(chart, 44100)
    assert effect.triggers[:5] == tuple(clock.frame(p) for p in (0, 480, 720, 1200, 1680))


def test_legacy_filter_gain_only_modifies_builtin_filters() -> None:
    chart = parse_kson(
        document(
            audio={
                "audio_effect": {
                    "laser": {
                        "legacy": {"filter_gain": [[0, 0.75]]},
                        "def": [
                            ["high_pass_filter", {"type": "high_pass_filter", "v": {"q": "1"}}]
                        ],
                    }
                }
            }
        )
    ).chart
    changes = compile_chart_audio(chart).changes
    assert {(c.effect, c.parameter, c.value) for c in changes} == {
        ("peaking_filter", "gain", "75%"),
        ("low_pass_filter", "q", "4.4"),
    }


def test_unimplemented_audio_remains_explicit() -> None:
    chart = parse_kson(
        document(
            audio={
                "bgm": {"legacy": {"fp_filenames": ["f.ogg"]}},
                "key_sound": {"laser": {"slam_event": {"slam_up": [0]}}},
                "audio_effect": {"fx": {"def": [["other", {"type": "future"}]]}},
                "new_extension": True,
            }
        )
    ).chart
    program = compile_chart_audio(chart)
    assert set(program.unsupported_paths) == {
        "/audio/bgm/legacy/fp_filenames",
        "/audio/key_sound/laser",
        "/audio/audio_effect/fx/def/0",
        "/audio/new_extension",
    }
    assert all(path not in program.coverage_paths for path in program.unsupported_paths)


def test_render_coverage_disables_native_processing_and_preserves_chips() -> None:
    chart = parse_kson(
        document(
            note={"fx": [[0, 120, [240, 240]], []], "laser": [[[0, [[0, 0], [480, 1]]]], []]},
            audio={
                "audio_effect": {"fx": {"long_event": {"gate": [[240], []]}}},
                "key_sound": {"fx": {"chip_event": {"clap": [[0], []]}}},
            },
        )
    ).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    with pytest.raises(UnsupportedFeaturesError):
        convert_chart(chart, options=ConversionOptions(strict=True), profile=DEFAULT_PROFILE)
    rendered = apply_rendered_audio(
        result, chart, compile_chart_audio(chart), options=ConversionOptions(strict=True)
    )
    assert [
        n.sample for t in rendered.chart.tracks for n in t.events if isinstance(n, VoxFxChip)
    ] == [255, 0]
    assert all(
        n.effect == 6
        for t in rendered.chart.tracks
        for n in t.events
        if isinstance(n, VoxLaserPoint)
    )
    assert all(n.effect == 6 for n in rendered.chart.original_left)
    assert not rendered.chart.auto_tab
    assert not any(f.status == FeatureStatus.UNSUPPORTED for f in rendered.report.features)


def test_render_coverage_cannot_hide_non_audio_strict_omissions() -> None:
    chart = parse_kson(document(beat={"bpm": [[0, 120]], "stop": [[240, 120]]})).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    with pytest.raises(UnsupportedFeaturesError):
        apply_rendered_audio(
            result, chart, compile_chart_audio(chart), options=ConversionOptions(strict=True)
        )


def test_direct_keysound_models_are_validated() -> None:
    chart = parse_kson(document()).chart
    invalid = replace(
        chart,
        audio=replace(
            chart.audio,
            key_sound=KeySoundInfo((ChipKeySound(KsonPulse(0), 0, "clap", -1, True, "/chip"),)),
        ),
    )
    with pytest.raises(KsonValidationError):
        compile_chart_audio(invalid)


def test_compiler_only_omissions_are_enforced_by_render_coverage() -> None:
    chart = parse_kson(document()).chart
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    program = replace(compile_chart_audio(chart), unsupported_paths=("/audio/custom",))
    with pytest.raises(UnsupportedFeaturesError) as caught:
        apply_rendered_audio(result, chart, program, options=ConversionOptions(strict=True))
    assert any(
        f.json_pointer == "/audio/custom" and f.status == FeatureStatus.UNSUPPORTED
        for f in caught.value.report.features
    )


def test_rendering_parent_audio_feature_does_not_cover_unknown_children() -> None:
    chart = parse_kson(
        document(
            audio={
                "audio_effect": {"fx": {"def": [["R", {"type": "retrigger", "unexpected": True}]]}}
            }
        )
    ).chart
    program = compile_chart_audio(chart)
    result = convert_chart(chart, options=ConversionOptions(), profile=DEFAULT_PROFILE)
    assert "/audio/audio_effect/fx/def/0" in program.coverage_paths
    with pytest.raises(UnsupportedFeaturesError) as caught:
        apply_rendered_audio(result, chart, program, options=ConversionOptions(strict=True))
    assert any(
        f.json_pointer == "/audio/audio_effect/fx/def/0/1/unexpected"
        and f.status == FeatureStatus.UNSUPPORTED
        for f in caught.value.report.features
    )


@pytest.mark.parametrize(
    ("version", "polyphony", "release_time"),
    [
        ("", 1, None),
        ("99", 1, None),
        ("100", 10, "1/16"),
        ("170", 10, "1/16"),
        ("171", 1, "1/16"),
        ("199", 1, "1/16"),
        ("200", 1, None),
    ],
)
def test_source_compatibility_preserves_sample_voices_and_sidechain_defaults(
    version: str, polyphony: int, release_time: str | None
) -> None:
    chart = parse_kson(
        document(
            compat={"ksh_version": version, "ksh_unknown": {"meta": {"custom": "retained"}}},
            audio={
                "audio_effect": {
                    "fx": {
                        "def": [
                            ["S", {"type": "sidechain"}],
                            ["Explicit", {"type": "sidechain", "v": {"release_time": "1/4"}}],
                        ]
                    }
                }
            },
        )
    ).chart
    assert chart.compatibility.ksh_version == version
    assert next(f for f in chart.retained if f.path == "/compat").value
    program = compile_chart_audio(chart)
    assert program.key_sound_polyphony == polyphony
    assert program.to_dict()["key_sound_polyphony"] == polyphony
    sidechain = next(e for e in program.effects if e.name == "S")
    assert dict(sidechain.parameters).get("release_time") == release_time
    assert (
        dict(next(e for e in program.effects if e.name == "Explicit").parameters)["release_time"]
        == "1/4"
    )
    assert not next(
        e for e in program.effects if e.bus == "fx" and e.name == "sidechain"
    ).parameters


def test_source_compatibility_requires_string_version() -> None:
    with pytest.raises(KsonValidationError):
        parse_kson(document(compat={"ksh_version": 170}))


@given(st.integers(30, 400), st.lists(st.integers(0, 5000), min_size=1, max_size=30))
def test_audio_timing_is_monotonic_and_programs_are_deterministic(
    bpm: int, pulses: list[int]
) -> None:
    chart = parse_kson(document(beat={"bpm": [[0, bpm]]})).chart
    clock = AudioClock(chart, 44100)
    frames = [clock.frame(p) for p in sorted(pulses)]
    assert frames == sorted(frames)
    assert compile_chart_audio(chart).to_dict() == compile_chart_audio(chart).to_dict()
