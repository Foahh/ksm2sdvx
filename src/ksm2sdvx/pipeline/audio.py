"""Resolve chart audio resources and compose rendering with S3V encoding."""

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from ksm2sdvx.chart import KsonChart, load_kson
from ksm2sdvx.chart.audio import ChartAudioProgram, compile_chart_audio
from ksm2sdvx.common.diagnostics import Diagnostic, Severity
from ksm2sdvx.common.types import JsonValue, json_ready
from ksm2sdvx.music import FfmpegMusicProcessor, MusicRequest, MusicResult, S3vMusicSettings
from ksm2sdvx.music.errors import MusicError
from ksm2sdvx.music.render_models import (
    AudioRenderer,
    AudioRenderRequest,
    AudioRenderResult,
    AudioSource,
)
from ksm2sdvx.music.renderer import NativeAudioRenderer, bundled_preset
from ksm2sdvx.resources.discovery import discover_resources, resolve_resource
from ksm2sdvx.resources.models import ResourceInput, ResourceRecord, ResourceReference, ResourceUse


@dataclass(frozen=True, slots=True)
class ChartAudioOutput:
    destination: Path
    report_path: Path
    diagnostics: tuple[Diagnostic, ...]


def audio_measurements(result: MusicResult) -> dict[str, JsonValue]:
    """Describe normalization independently of temporary processing paths."""
    return {
        "gain_db": result.gain_db,
        "measured_input_lufs": result.measurement.integrated_lufs if result.measurement else None,
        "measured_input_dbtp": result.measurement.true_peak_dbtp if result.measurement else None,
        "measured_output_lufs": (
            result.output_measurement.integrated_lufs if result.output_measurement else None
        ),
        "measured_output_dbtp": (
            result.output_measurement.true_peak_dbtp if result.output_measurement else None
        ),
    }


def rendering_report(result: AudioRenderResult, source: str) -> dict[str, JsonValue]:
    return replace(
        result, diagnostics=tuple(replace(d, source_path=source) for d in result.diagnostics)
    ).to_dict()


def rendered_music_resource(result: AudioRenderResult, source: Path) -> ResourceRecord:
    return ResourceRecord(
        result.resource.path.name,
        result.resource.path,
        False,
        True,
        (ResourceUse(source, "music", "/audio"),),
    )


def render_chart_audio(
    chart: KsonChart,
    program: ChartAudioProgram,
    *,
    source: Path,
    root: Path,
    destination: Path,
    renderer: AudioRenderer,
) -> AudioRenderResult:
    """Resolve only inputs consumed by the audio program, within its package root."""
    bgm = chart.audio.bgm
    if bgm is None or not bgm.filename:
        raise MusicError("Chart audio rendering requires audio.bgm.filename")
    music_ref = ResourceReference(bgm.filename, "music", "/audio/bgm/filename")
    references = (music_ref, *program.resources)
    inventory = discover_resources((ResourceInput(source, ref) for ref in references), root=root)
    errors = tuple(d for d in inventory.diagnostics if d.severity == Severity.ERROR)
    if errors:
        raise MusicError("Audio resource discovery failed: " + "; ".join(d.message for d in errors))
    music = resolve_resource(music_ref, source, root)
    assert music is not None
    tracks: dict[str, AudioSource] = {}
    samples: dict[str, AudioSource] = {}
    for reference in program.resources:
        path = (
            bundled_preset(reference.name)
            if reference.preset
            else resolve_resource(reference, source, root)
        )
        assert path is not None
        item = AudioSource(reference.name, path)
        if reference.role == "effect_audio":
            tracks[item.id] = item
        elif reference.role == "keysound":
            samples[item.id] = item
        else:
            raise MusicError(f"Unexpected rendered resource role: {reference.role}")
    result = renderer.render(
        AudioRenderRequest(
            program,
            destination,
            AudioSource("main", music),
            tuple(tracks.values()),
            tuple(samples.values()),
        )
    )
    if result.resource.path.resolve() != destination.resolve() or not destination.is_file():
        raise MusicError("Audio renderer did not produce its requested output")
    return result


def _convert_chart_audio_file(
    source: Path,
    *,
    output: Path | None,
    strict: bool,
    target_lufs: float,
    true_peak_dbtp: float,
    gain_db: float | None,
    ffmpeg: str,
    renderer: AudioRenderer | None,
    processor: FfmpegMusicProcessor | None,
) -> ChartAudioOutput:
    source = source.resolve()
    parsed = load_kson(source)
    program = compile_chart_audio(parsed.chart)
    if strict and program.unsupported_paths:
        raise MusicError(
            "Strict audio rendering would omit: " + ", ".join(program.unsupported_paths)
        )
    destination = (output or Path("output") / f"{source.stem}.s3v").resolve()
    if destination.suffix.lower() != ".s3v":
        raise MusicError("Chart audio output must have a .s3v extension")
    report_path = destination.with_suffix(".report.json")
    protected = {source}
    if parsed.chart.audio.bgm is not None and parsed.chart.audio.bgm.filename:
        original = resolve_resource(
            ResourceReference(parsed.chart.audio.bgm.filename, "music", "/audio/bgm/filename"),
            source,
            source.parent,
        )
        assert original is not None
        protected.add(original)
    for reference in program.resources:
        resource = resolve_resource(reference, source, source.parent)
        if resource is not None:
            protected.add(resource)
    if protected.intersection((destination, report_path)):
        raise MusicError("Audio output must not overwrite a source resource")
    if destination.is_dir() or report_path.is_dir():
        raise MusicError("Audio output or report destination is a directory")
    settings = S3vMusicSettings(
        target_lufs=target_lufs, true_peak_dbtp=true_peak_dbtp, gain_db=gain_db
    )
    renderer = renderer if renderer is not None else NativeAudioRenderer(ffmpeg=ffmpeg)
    processor = processor if processor is not None else FfmpegMusicProcessor(ffmpeg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ksm2sdvx-chart-audio-", dir=destination.parent
    ) as temp:
        workspace = Path(temp)
        rendered = render_chart_audio(
            parsed.chart,
            program,
            source=source,
            root=source.parent,
            destination=workspace / "rendered.wav",
            renderer=renderer,
        )
        music = processor.process(
            MusicRequest(
                rendered_music_resource(rendered, source), workspace / destination.name, settings
            )
        )
        diagnostics = tuple(
            replace(d, source_path=source.name)
            for d in (
                *parsed.diagnostics,
                *program.diagnostics,
                *rendered.diagnostics,
                *music.diagnostics,
            )
        )
        report: dict[str, JsonValue] = {
            "schema_version": 1,
            "source": source.name,
            "rendering": rendering_report(rendered, source.name),
            "coverage": program.coverage_paths,
            "unsupported": program.unsupported_paths,
            "normalization": {
                "target_lufs": target_lufs,
                "true_peak_dbtp": true_peak_dbtp,
                **audio_measurements(music),
            },
            "diagnostics": tuple(d.to_dict() for d in diagnostics),
        }
        staged_report = workspace / report_path.name
        staged_report.write_text(
            json.dumps(json_ready(report), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(music.resource.path, destination)
        os.replace(staged_report, report_path)
    return ChartAudioOutput(destination, report_path, diagnostics)


def convert_chart_audio_file(
    source: Path,
    *,
    output: Path | None = None,
    strict: bool = False,
    target_lufs: float = -11.0,
    true_peak_dbtp: float = -1.0,
    gain_db: float | None = None,
    ffmpeg: str = "ffmpeg",
    renderer: AudioRenderer | None = None,
    processor: FfmpegMusicProcessor | None = None,
) -> ChartAudioOutput:
    """Render authored chart audio, normalize it, and stage the audio/report pair."""
    try:
        return _convert_chart_audio_file(
            source,
            output=output,
            strict=strict,
            target_lufs=target_lufs,
            true_peak_dbtp=true_peak_dbtp,
            gain_db=gain_db,
            ffmpeg=ffmpeg,
            renderer=renderer,
            processor=processor,
        )
    except OSError as exc:
        raise MusicError(f"Chart audio filesystem operation failed: {exc}") from exc
