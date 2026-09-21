"""Coordinate pure conversion passes into a validated target model."""

from dataclasses import dataclass
from types import MappingProxyType

from ksm2sdvx.chart.conversion.beat import convert_bpms
from ksm2sdvx.chart.conversion.buttons import convert_buttons
from ksm2sdvx.chart.conversion.camera import attach_spins, convert_camera
from ksm2sdvx.chart.conversion.effects import report_unconverted
from ksm2sdvx.chart.conversion.lasers import convert_lasers
from ksm2sdvx.chart.conversion.options import ConversionOptions
from ksm2sdvx.chart.conversion.profiles import VoxProfile
from ksm2sdvx.chart.conversion.report import ConversionReport, ReportBuilder
from ksm2sdvx.chart.conversion.scroll import convert_scroll_speed
from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.kson.model import KsonChart
from ksm2sdvx.chart.kson.validation import validate_kson
from ksm2sdvx.chart.types import KsonPulse
from ksm2sdvx.chart.vox.effects import (
    EffectPair,
    NoEffect,
    ParameterAssignment,
)
from ksm2sdvx.chart.vox.model import VoxChart, VoxMeterEvent, VoxTrack
from ksm2sdvx.chart.vox.validation import validate_vox
from ksm2sdvx.common.diagnostics import FeatureStatus


@dataclass(frozen=True, slots=True)
class ConversionResult:
    chart: VoxChart
    report: ConversionReport


class UnsupportedFeaturesError(ConversionError):
    def __init__(self, report: ConversionReport) -> None:
        self.report = report
        omitted = [f.json_pointer for f in report.features if f.status == FeatureStatus.UNSUPPORTED]
        super().__init__("Strict conversion would omit: " + ", ".join(omitted))


def convert_chart(
    chart: KsonChart, *, options: ConversionOptions, profile: VoxProfile
) -> ConversionResult:
    validate_kson(chart)
    options.validate()
    profile.validate()
    report = ReportBuilder()
    timeline = Timeline(chart.beat.time_signatures)
    bpms, beat_end = convert_bpms(chart.beat, timeline, report)
    buttons, button_end = convert_buttons(chart.note, timeline, report)
    samples = convert_lasers(chart.note, timeline, options.curve_step, report)
    samples, spin_end = attach_spins(samples, chart.camera.spins, report)
    scroll, scroll_end = convert_scroll_speed(
        chart.beat.scroll_speed, timeline, options.curve_step, report
    )
    end = max(
        beat_end,
        button_end,
        spin_end,
        scroll_end,
        *(int(p) for p in timeline.starts),
        *(s.pulse for s in samples),
    )
    controllers, tilt_modes, camera_end = convert_camera(
        chart.camera,
        timeline,
        options,
        profile,
        report,
        end,
        tuple(e.pulse for e in chart.beat.bpm),
    )
    controllers = tuple(sorted((*controllers, *scroll), key=lambda event: event.position))
    left = tuple(s.event for s in samples if s.track == 1)
    right = tuple(s.event for s in samples if s.track == 8)
    tracks = tuple(
        sorted((*buttons, VoxTrack(1, left), VoxTrack(8, right)), key=lambda t: t.number)
    )
    meters = tuple(
        VoxMeterEvent(timeline.position(p), e.numerator, e.denominator)
        for p, e in zip(timeline.starts, chart.beat.time_signatures, strict=True)
    )
    # Include supported timing and controller events, even when no note reaches them.
    end = max(end, camera_end)
    report.record("beat", FeatureStatus.CONVERTED, "/beat")
    report.record("notes", FeatureStatus.CONVERTED, "/note")
    report_unconverted(chart, report)
    target = VoxChart(
        meters,
        bpms,
        tilt_modes,
        tracks,
        tuple(s.event for s in samples if s.track == 1 and s.control_node),
        tuple(s.event for s in samples if s.track == 8 and s.control_node),
        controllers,
        timeline.position(end),
        profile.laser_effects,
        tuple(EffectPair(NoEffect(), NoEffect()) for _ in range(12)),
        tuple(ParameterAssignment(i // 2) for i in range(24)),
    )
    validate_vox(target)
    final_report = ConversionReport(
        profile.name,
        options,
        KsonPulse(end),
        MappingProxyType(dict(report.counts)),
        tuple(report.diagnostics),
        tuple(report.features),
    )
    if options.strict and any(f.status == FeatureStatus.UNSUPPORTED for f in report.features):
        raise UnsupportedFeaturesError(final_report)
    return ConversionResult(target, final_report)
