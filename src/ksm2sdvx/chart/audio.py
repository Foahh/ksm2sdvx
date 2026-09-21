"""Compile source chart audio without reading files or invoking a renderer."""

import re
from dataclasses import replace

from ksm2sdvx.chart.audio_model import (
    AudioChange,
    AudioEffect,
    AudioFxInvocation,
    AudioHold,
    AudioKeySound,
    AudioLaser,
    AudioLaserInvocation,
    AudioLaserPoint,
    AudioTempo,
    ChartAudioProgram,
)
from ksm2sdvx.chart.audio_timing import AudioClock, effect_triggers
from ksm2sdvx.chart.conversion.converter import ConversionResult, UnsupportedFeaturesError
from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.kson.model import EffectDefinition, EffectInvocation, KsonChart
from ksm2sdvx.chart.kson.validation import validate_kson
from ksm2sdvx.chart.vox.effects import EffectPair, NoEffect, ParameterAssignment
from ksm2sdvx.chart.vox.model import VoxFxChip, VoxFxHold, VoxLaserPoint
from ksm2sdvx.chart.vox.validation import validate_vox
from ksm2sdvx.common.diagnostics import Diagnostic, FeatureResult, FeatureStatus, Severity, Stage
from ksm2sdvx.resources.models import ResourceReference

FX_DEFAULTS = (
    "retrigger",
    "gate",
    "flanger",
    "pitch_shift",
    "bitcrusher",
    "phaser",
    "wobble",
    "tapestop",
    "echo",
    "sidechain",
)
LASER_DEFAULTS = ("peaking_filter", "high_pass_filter", "low_pass_filter", "bitcrusher")
EFFECT_TYPES = frozenset((*FX_DEFAULTS, *LASER_DEFAULTS, "switch_audio"))


def compile_chart_audio(
    chart: KsonChart, *, duration_frames: int | None = None, sample_rate: int = 44100
) -> ChartAudioProgram:
    """Compile audio instructions; report unsupported audio without claiming a render.

    ``duration_frames`` is the chart-aligned output length, when known. Source
    offsets are applied only by the renderer, never to chart event timestamps.
    """
    validate_kson(chart)
    if type(sample_rate) is not int or sample_rate != 44100:
        raise ConversionError("Chart audio rendering requires a sample rate of 44100 Hz")
    if duration_frames is not None and (type(duration_frames) is not int or duration_frames < 0):
        raise ConversionError("Audio duration must be a nonnegative integer frame count")
    clock = AudioClock(chart, sample_rate)
    version_match = re.match(r"\s*([+-]?\d+)", chart.compatibility.ksh_version)
    compatibility_version = int(version_match[1]) if version_match else 0
    last_pulse = max(
        (
            0,
            *(
                n.pulse + n.duration
                for lanes in (chart.note.bt, chart.note.fx)
                for lane in lanes
                for n in lane
            ),
            *(s.pulse + s.points[-1].offset for lane in chart.note.laser for s in lane),
            *(
                e.pulse
                for group in (chart.audio.fx, chart.audio.laser)
                for e in (*group.changes, *group.invocations)
            ),
            *(e.pulse for e in chart.audio.key_sound.chips),
        )
    )
    end_frame = max(duration_frames or 0, clock.frame(last_pulse))
    diagnostics: list[Diagnostic] = []
    unsupported: list[str] = []
    coverage: list[str] = []
    resources: dict[tuple[str, str], ResourceReference] = {}

    def omission(path: str, message: str, pulse: int | None = None) -> None:
        unsupported.append(path)
        diagnostics.append(
            Diagnostic(
                "UNSUPPORTED_AUDIO_FEATURE",
                Severity.WARNING,
                Stage.CONVERT,
                message,
                "audio_effect",
                path,
                pulse,
            )
        )

    effects: list[AudioEffect] = []
    changes: list[AudioChange] = []
    known: dict[str, set[str]] = {}
    for bus, group, defaults in (
        ("fx", chart.audio.fx, FX_DEFAULTS),
        ("laser", chart.audio.laser, LASER_DEFAULTS),
    ):
        base = f"/audio/audio_effect/{bus}"
        named = {d.name for d in group.definitions}
        definitions = [
            (EffectDefinition(name, name, ()), True, "") for name in defaults if name not in named
        ]
        definitions.extend((d, False, f"{base}/def/{i}") for i, d in enumerate(group.definitions))
        known[bus] = set()
        for definition, builtin, path in definitions:
            if definition.kind not in EFFECT_TYPES:
                omission(path, f"Audio effect type {definition.kind!r} is not rendered.")
                continue
            if (
                not builtin
                and definition.kind == "sidechain"
                and 100 <= compatibility_version < 200
                and "release_time" not in dict(definition.parameters)
            ):
                definition = replace(
                    definition, parameters=(*definition.parameters, ("release_time", "1/16"))
                )
            known[bus].add(definition.name)
            effects.append(
                AudioEffect(
                    definition.name,
                    definition.kind,
                    bus,
                    definition.parameters,
                    effect_triggers(definition, group, clock, end_frame),
                    builtin,
                )
            )
            if path:
                coverage.append(path)
            filename = dict(definition.parameters).get("filename")
            if definition.kind == "switch_audio" and filename:
                resources[(filename, "effect_audio")] = ResourceReference(
                    filename, "effect_audio", path + "/1/v/filename"
                )
        for change in group.changes:
            if change.effect not in known[bus]:
                omission(
                    change.path, f"Audio effect {change.effect!r} is not defined.", change.pulse
                )
                continue
            changes.append(
                AudioChange(
                    clock.frame(change.pulse), bus, change.effect, change.parameter, change.value
                )
            )
            coverage.append(change.path)
        for field in group.retained:
            omission(field.path, "This audio parameter is not rendered.")
        if group.peaking_filter_delay:
            coverage.append(base + "/peaking_filter_delay")
        for event in group.filter_gain:
            coverage.append(event.path)
            # Legacy gain only changes filters that have not been redefined.
            if any(e.value != 0.5 for e in group.filter_gain):
                for name, parameter, value in (
                    ("peaking_filter", "gain", f"{int(event.value * 100 + 0.5)}%"),
                    ("high_pass_filter", "q", str(2 + 6 * event.value)),
                    ("low_pass_filter", "q", str(2 + 3.2 * event.value)),
                ):
                    if name not in named:
                        changes.append(
                            AudioChange(clock.frame(event.pulse), bus, name, parameter, value)
                        )

    holds: list[AudioHold] = []
    fx: list[AudioFxInvocation] = []
    for lane, notes in enumerate(chart.note.fx):
        invocations: dict[int, EffectInvocation] = {}
        for event in chart.audio.fx.invocations:
            if event.lane != lane:
                continue
            if event.effect and event.effect not in known["fx"]:
                omission(event.path, f"Audio effect {event.effect!r} is not defined.", event.pulse)
            else:
                coverage.append(event.path)
            invocations[event.pulse] = event
        consumed: set[int] = set()
        for note in notes:
            if not note.duration:
                continue
            hold_end = note.pulse + note.duration
            holds.append(AudioHold(clock.frame(note.pulse), clock.frame(hold_end), lane))
            events = sorted(
                (e for e in invocations.values() if note.pulse <= e.pulse < hold_end),
                key=lambda e: e.pulse,
            )
            for index, event in enumerate(events):
                consumed.add(event.pulse)
                if event.effect not in known["fx"]:
                    continue
                end = events[index + 1].pulse if index + 1 < len(events) else hold_end
                fx.append(
                    AudioFxInvocation(
                        clock.frame(event.pulse),
                        clock.frame(end),
                        lane,
                        clock.frame(note.pulse),
                        event.effect,
                        event.parameters,
                    )
                )
        for event in invocations.values():
            if event.pulse not in consumed:
                diagnostics.append(
                    Diagnostic(
                        "IGNORED_FX_EVENT",
                        Severity.INFO,
                        Stage.CONVERT,
                        "FX invocation outside a hold has no audio effect.",
                        "audio_effect",
                        event.path,
                        event.pulse,
                    )
                )

    default_laser = next(
        (
            effect.name
            for effect in effects
            if effect.bus == "laser"
            and effect.name == "peaking_filter"
            and effect.type != "switch_audio"
        ),
        None,
    )
    laser_events = {0: AudioLaserInvocation(0, default_laser)}
    for event in chart.audio.laser.invocations:
        effect = event.effect if event.effect in known["laser"] else None
        laser_events[event.pulse] = AudioLaserInvocation(clock.frame(event.pulse), effect)
        if event.effect and effect is None:
            omission(event.path, f"Audio effect {event.effect!r} is not defined.", event.pulse)
        else:
            coverage.append(event.path)
    lasers = tuple(
        AudioLaser(
            lane,
            clock.frame(section.pulse),
            clock.frame(section.pulse + section.points[-1].offset),
            tuple(
                AudioLaserPoint(
                    clock.frame(section.pulse + point.offset),
                    float(section.pulse + point.offset),
                    point.incoming,
                    point.outgoing,
                    point.control.x,
                    point.control.y,
                )
                for point in section.points
            ),
        )
        for lane, sections in enumerate(chart.note.laser)
        for section in sections
    )
    chips: list[AudioKeySound] = []
    positions = {
        (lane, note.pulse)
        for lane, notes in enumerate(chart.note.fx)
        for note in notes
        if not note.duration
    }
    for chip in chart.audio.key_sound.chips:
        coverage.append(chip.path)
        if (chip.lane, chip.pulse) not in positions:
            diagnostics.append(
                Diagnostic(
                    "IGNORED_CHIP_KEYSOUND",
                    Severity.INFO,
                    Stage.CONVERT,
                    "Keysound invocation without an FX chip has no audio effect.",
                    "keysound",
                    chip.path,
                    chip.pulse,
                )
            )
            continue
        chips.append(
            AudioKeySound(clock.frame(chip.pulse), chip.lane, chip.sample, chip.volume, chip.pulse)
        )
        resources[(chip.sample, "keysound")] = ResourceReference(
            chip.sample, "keysound", chip.path, chip.preset
        )
    for field in chart.audio.key_sound.laser:
        omission(
            field.path,
            "Custom laser slam sounds and volume changes are not rendered; arcade slam feedback is retained.",
        )
    if chart.audio.bgm and chart.audio.bgm.legacy_filenames:
        omission("/audio/bgm/legacy/fp_filenames", "Legacy alternate BGM routing is not rendered.")
    for field in chart.extensions:
        if field.path.startswith("/audio/"):
            omission(field.path, "Unknown audio extension is not rendered.")
    bgm = chart.audio.bgm
    return ChartAudioProgram(
        sample_rate,
        end_frame,
        round((bgm.offset if bgm else 0) * sample_rate / 1000),
        bgm.volume if bgm else 1.0,
        tuple(AudioTempo(clock.frame(e.pulse), float(e.pulse), e.bpm) for e in chart.beat.bpm),
        tuple(effects),
        tuple(sorted(changes, key=lambda e: e.frame)),
        tuple(sorted(fx, key=lambda e: (e.start_frame, e.lane))),
        tuple(holds),
        tuple(e for _, e in sorted(laser_events.items())),
        lasers,
        tuple(sorted(chips, key=lambda e: (e.frame, e.lane))),
        round(chart.audio.laser.peaking_filter_delay * sample_rate / 1000),
        tuple(resources.values()),
        tuple(dict.fromkeys(coverage)),
        tuple(diagnostics),
        tuple(dict.fromkeys(unsupported)),
        10 if 100 <= compatibility_version < 171 else 1,
    )


def apply_rendered_audio(
    result: ConversionResult,
    chart: KsonChart,
    program: ChartAudioProgram,
    *,
    options: ConversionOptions,
    keysound_sample: int = 0,
) -> ConversionResult:
    """Apply a successfully rendered program to VOX and then enforce strict policy.

    The application calls this only after the renderer has completed successfully.
    Coverage is limited to exact source paths compiled into the audio program.
    A nonzero keysound_sample requires a matching silent native sample bank.
    """
    options.validate()
    if type(keysound_sample) is not int or not 0 <= keysound_sample <= 14:
        raise ConversionError("Rendered keysound sample must be an integer from 0 to 14")
    unsupported = frozenset(program.unsupported_paths)
    coverage = frozenset(program.coverage_paths) - unsupported
    existing_paths = {f.json_pointer for f in result.report.features}
    report = replace(
        result.report,
        options=options,
        diagnostics=tuple(d for d in result.report.diagnostics if d.json_pointer not in coverage)
        + program.diagnostics,
        features=tuple(
            replace(f, status=FeatureStatus.UNSUPPORTED)
            if f.json_pointer in unsupported
            else replace(f, status=FeatureStatus.CONVERTED)
            if f.json_pointer in coverage
            else f
            for f in result.report.features
        )
        + tuple(
            FeatureResult("audio_effect", FeatureStatus.UNSUPPORTED, path)
            for path in program.unsupported_paths
            if path not in existing_paths
        )
        + (FeatureResult("rendered_audio", FeatureStatus.CONVERTED, "/audio"),),
    )
    if options.strict and any(f.status == FeatureStatus.UNSUPPORTED for f in report.features):
        raise UnsupportedFeaturesError(report)
    timeline = Timeline(chart.beat.time_signatures)
    chips = {(2 if c.lane == 0 else 7, timeline.position(c.pulse)) for c in program.keysounds}
    tracks = tuple(
        replace(
            track,
            events=tuple(
                replace(event, effect=6)
                if isinstance(event, VoxLaserPoint)
                else replace(
                    event, sample=keysound_sample if (track.number, event.position) in chips else 0
                )
                if isinstance(event, VoxFxChip)
                else replace(event, effect_pair=2)
                if isinstance(event, VoxFxHold)
                else event
                for event in track.events
            ),
        )
        for track in result.chart.tracks
    )
    target = replace(
        result.chart,
        tracks=tracks,
        original_left=tuple(replace(e, effect=6) for e in result.chart.original_left),
        original_right=tuple(replace(e, effect=6) for e in result.chart.original_right),
        fx_effects=tuple(EffectPair(NoEffect(), NoEffect()) for _ in range(12)),
        parameter_assignments=tuple(ParameterAssignment(i // 2) for i in range(24)),
        auto_tab=(),
    )
    validate_vox(target)
    return ConversionResult(target, report)
