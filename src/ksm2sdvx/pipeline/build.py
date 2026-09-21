"""Compose chart, metadata, audio and jackets into a new LayeredFS mod."""

import os
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path, PurePosixPath

from ksm2sdvx.chart import (
    ConversionOptions,
    ConversionResult,
    KsonChart,
    VoxProfile,
    convert_chart,
    load_kson,
)
from ksm2sdvx.chart.audio import ChartAudioProgram, apply_rendered_audio, compile_chart_audio
from ksm2sdvx.common.diagnostics import Diagnostic, Severity, Stage
from ksm2sdvx.common.types import JsonValue
from ksm2sdvx.jacket import (
    FfmpegJacketProcessor,
    JacketRequest,
    JacketSettings,
    JacketSize,
)
from ksm2sdvx.metadata import (
    ChartAssignment,
    ChartMetadata,
    ChartSlot,
    MetadataField,
    PackageMetadata,
    SdvxMetadataConverter,
    SdvxMetadataSettings,
    load_music_database,
    serialize_music_database,
)
from ksm2sdvx.music import FfmpegMusicProcessor, MusicRequest, S3vMusicSettings
from ksm2sdvx.music.render_models import AudioRenderer
from ksm2sdvx.music.renderer import NativeAudioRenderer
from ksm2sdvx.music.sampler import SILENT_KEYSOUND_SAMPLE, write_silent_keysound_bank
from ksm2sdvx.pipeline.audio import (
    audio_measurements,
    render_chart_audio,
    rendered_music_resource,
    rendering_report,
)
from ksm2sdvx.pipeline.config import ChartInput, PackageConfig
from ksm2sdvx.pipeline.errors import PackageError
from ksm2sdvx.pipeline.models import PackageChart, PackageResource, PackageWriteResult, SdvxPackage
from ksm2sdvx.pipeline.writer import LayeredFsPackageWriter
from ksm2sdvx.resources import discover_resources
from ksm2sdvx.resources.discovery import resolve_resource
from ksm2sdvx.resources.models import (
    ProcessedResource,
    ResourceInput,
    ResourceRecord,
    ResourceReference,
)


@dataclass(frozen=True, slots=True)
class _Chart:
    binding: ChartInput
    source: KsonChart
    conversion: ConversionResult
    program: ChartAudioProgram


def _portable_diagnostic(diagnostic: Diagnostic, root: Path) -> Diagnostic:
    if diagnostic.source_path is None:
        return diagnostic
    path = Path(diagnostic.source_path)
    if not path.is_absolute():
        return replace(diagnostic, source_path=path.as_posix())
    if not path.is_relative_to(root):
        raise PackageError("A component diagnostic refers to a source outside the package root")
    return replace(diagnostic, source_path=path.relative_to(root).as_posix())


def _owned_resource(assets: tuple[ResourceRecord, ...], chart: Path, role: str) -> ResourceRecord:
    matches = tuple(
        asset
        for asset in assets
        if any(use.source == chart and use.role == role for use in asset.uses)
    )
    if len(matches) != 1 or matches[0].preset or matches[0].resolved_path is None:
        raise PackageError(
            f"Each chart requires one file resource for {role}; presets need an explicit file"
        )
    return matches[0]


def _load_charts(
    config: PackageConfig,
    options: ConversionOptions,
    profile: VoxProfile,
) -> tuple[tuple[_Chart, ...], tuple[ResourceRecord, ...], list[Diagnostic]]:
    root = config.root.resolve()
    if not root.is_dir() or not config.charts:
        raise PackageError("Package creation requires a source root and at least one chart")
    charts: list[_Chart] = []
    references: list[ResourceInput] = []
    diagnostics: list[Diagnostic] = []
    for binding in config.charts:
        path = binding.path.resolve()
        if not path.is_relative_to(root):
            raise PackageError("Chart escapes the source root")
        parsed = load_kson(path)
        converted = convert_chart(
            parsed.chart, options=replace(options, strict=False), profile=profile
        )
        program = compile_chart_audio(parsed.chart)
        charts.append(_Chart(replace(binding, path=path), parsed.chart, converted, program))
        relative = path.relative_to(root).as_posix()
        diagnostics.extend(replace(d, source_path=relative) for d in parsed.diagnostics)
        jacket = binding.jacket.source or config.jacket.source
        references.extend(
            ResourceInput(path, ref)
            for ref in parsed.chart.assets
            if not (jacket is not None and ref.role == "jacket")
        )
        if jacket is not None:
            jacket = jacket.resolve()
            if not jacket.is_relative_to(root):
                raise PackageError("Jacket escapes the source root")
            references.append(
                ResourceInput(
                    path,
                    ResourceReference(
                        Path(os.path.relpath(jacket, path.parent)).as_posix(),
                        "jacket",
                        "/package/jacket",
                    ),
                )
            )
    inventory = discover_resources(references, root=root)
    if any(d.severity == Severity.ERROR for d in inventory.diagnostics):
        raise PackageError(
            "Resource discovery failed: "
            + "; ".join(d.message for d in inventory.diagnostics if d.severity == Severity.ERROR)
        )
    return tuple(charts), inventory.assets, diagnostics


def _source_metadata(chart: _Chart) -> ChartMetadata:
    meta = chart.source.meta
    bgm = chart.source.audio.bgm
    if bgm is None or not bgm.filename:
        raise PackageError(
            "Every package chart must reference its music through audio.bgm.filename"
        )
    return ChartMetadata(
        chart.binding.path,
        meta.title,
        meta.artist,
        meta.chart_author,
        meta.difficulty,
        meta.level,
        meta.disp_bpm,
        bgm.offset,
        bgm.preview_offset,
        bgm.preview_duration,
        tuple(MetadataField(field.path, field.value) for field in meta.optional),
    )


def build_package(
    config: PackageConfig,
    *,
    game_data: Path,
    destination: Path,
    options: ConversionOptions,
    profile: VoxProfile,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    renderer: AudioRenderer | None = None,
) -> PackageWriteResult:
    """Build one explicitly grouped song; never modify the reference game data."""
    try:
        return _build_package(
            config,
            game_data=game_data,
            destination=destination,
            options=options,
            profile=profile,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            renderer=renderer,
        )
    except OSError as exc:
        raise PackageError(f"Package filesystem operation failed: {exc}") from exc


def _build_package(
    config: PackageConfig,
    *,
    game_data: Path,
    destination: Path,
    options: ConversionOptions,
    profile: VoxProfile,
    ffmpeg: str,
    ffprobe: str,
    renderer: AudioRenderer | None,
) -> PackageWriteResult:
    options.validate()
    profile.validate()
    config = replace(config, root=config.root.resolve())
    if any(chart.slot not in ChartSlot for chart in config.charts):
        raise PackageError("Package charts must use valid target slots")
    game_data = game_data.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(game_data):
        raise PackageError("Package output must be outside the reference game data directory")
    if destination.exists():
        raise PackageError("Package output already exists; choose a new destination")
    database = load_music_database(game_data / "others/music_db.xml")
    charts, assets, diagnostics = _load_charts(config, options, profile)
    jackets = {
        chart.binding.path: _owned_resource(assets, chart.binding.path, "jacket")
        for chart in charts
        if any(
            use.source == chart.binding.path and use.role == "jacket"
            for asset in assets
            for use in asset.uses
        )
    }
    if jackets and not (game_data / "graphics/s_jacket00.ifs").is_file():
        raise PackageError(
            "Reference data must contain graphics/s_jacket00.ifs for selector jackets"
        )
    for chart in charts:
        for field in chart.source.meta.optional:
            if field.path in {
                "/meta/jacket_filename",
                "/meta/jacket_author",
            } or field.path.endswith("_filename"):
                continue
            if options.strict:
                raise PackageError(f"Strict package conversion would omit metadata at {field.path}")
            diagnostics.append(
                Diagnostic(
                    "UNSUPPORTED_PACKAGE_METADATA",
                    Severity.WARNING,
                    Stage.PACKAGE,
                    "This source metadata field has no package output mapping.",
                    "metadata",
                    field.path,
                    source_path=str(chart.binding.path),
                )
            )
    for asset in assets:
        for use in asset.uses:
            owner = next(chart for chart in charts if chart.binding.path == use.source)
            consumed = any(
                reference.role == use.role
                and (
                    reference.name == asset.name
                    if reference.preset
                    else resolve_resource(reference, use.source, config.root) == asset.resolved_path
                )
                for reference in owner.program.resources
            )
            if use.role not in {"music", "jacket"} and not consumed:
                if options.strict:
                    raise PackageError(
                        f"Strict package conversion would omit a {use.role} resource"
                    )
                diagnostics.append(
                    Diagnostic(
                        "UNSUPPORTED_PACKAGE_RESOURCE",
                        Severity.WARNING,
                        Stage.PACKAGE,
                        f"The {use.role} resource is not included in the output package.",
                        use.role,
                        use.json_pointer,
                        source_path=str(use.source),
                    )
                )
    metadata_source = PackageMetadata(tuple(_source_metadata(chart) for chart in charts))
    assignments = tuple(
        ChartAssignment(
            chart.binding.path,
            ChartSlot(chart.binding.slot),
            chart.binding.jacket.author or config.jacket.author,
            chart.binding.level_tenths,
            chart.binding.max_exscore,
            price=chart.binding.price,
            limited=chart.binding.limited,
            jacket_print=chart.binding.jacket_print,
            jacket_mask=chart.binding.jacket_mask,
            radar=chart.binding.radar,
        )
        for chart in charts
    )
    bpms = tuple(event.bpm for chart in charts for event in chart.source.beat.bpm)
    converted_metadata = SdvxMetadataConverter().convert(
        metadata_source,
        settings=SdvxMetadataSettings(
            database=database,
            song_id=config.song_id,
            charts=assignments,
            ascii_name=config.name,
            title=config.title,
            artist=config.artist,
            bpm_min=min(bpms),
            bpm_max=max(bpms),
            title_yomigana=config.title_yomigana,
            artist_yomigana=config.artist_yomigana,
            volume=config.volume if config.volume is not None else 91,
            version=config.version if config.version is not None else 7,
            distribution_date=config.distribution_date or date.today(),
            bg_no=config.bg_no,
            genre=config.genre,
            is_fixed=config.is_fixed,
            demo_pri=config.demo_pri,
            inf_ver=config.inf_ver,
            license_text=config.license_text,
        ),
    )
    metadata = converted_metadata.metadata
    serialize_music_database(metadata)  # Validate text encoding before processing media.
    diagnostics.extend(converted_metadata.diagnostics)
    music = _owned_resource(assets, charts[0].binding.path, "music")
    bgm = charts[0].source.audio.bgm
    assert bgm is not None
    for chart in charts:
        other = chart.source.audio.bgm
        other_music = _owned_resource(assets, chart.binding.path, "music")
        if (
            other is None
            or other_music.resolved_path != music.resolved_path
            or (other.offset, other.volume, other.preview_offset, other.preview_duration)
            != (bgm.offset, bgm.volume, bgm.preview_offset, bgm.preview_duration)
        ):
            raise PackageError(
                "Charts in one song must share music, audio offset, volume and preview timing"
            )
    if bgm.preview_duration <= 0:
        raise PackageError("Package preview duration must be positive")
    music_processor = FfmpegMusicProcessor(ffmpeg=ffmpeg)
    renderer = renderer if renderer is not None else NativeAudioRenderer(ffmpeg=ffmpeg)
    jacket_processor = FfmpegJacketProcessor(ffmpeg=ffmpeg, ffprobe=ffprobe)
    resources: list[PackageResource] = []
    audio_reports: list[dict[str, JsonValue]] = []
    rendered_charts: list[_Chart] = []
    with tempfile.TemporaryDirectory(prefix="ksm2sdvx-media-") as temp:
        workspace = Path(temp)
        silent_bank: ProcessedResource | None = None
        audio_settings = S3vMusicSettings(
            target_lufs=config.target_lufs,
            true_peak_dbtp=config.true_peak_dbtp,
        )
        preview = music_processor.process_preview(
            MusicRequest(
                music,
                workspace / metadata.music_filename(preview=True),
                replace(
                    audio_settings,
                    offset_ms=0,
                    preview_start_ms=int(bgm.preview_offset),
                    preview_duration_ms=int(bgm.preview_duration),
                ),
            ),
        )
        resources.append(
            PackageResource(preview.resource, metadata.directory / preview.resource.path.name)
        )
        diagnostics.extend(preview.diagnostics)
        for chart, assignment in zip(charts, assignments, strict=True):
            rendered = render_chart_audio(
                chart.source,
                chart.program,
                source=chart.binding.path,
                root=config.root,
                destination=workspace / f"rendered_{assignment.slot.suffix}.wav",
                renderer=renderer,
            )
            sampler_filename: str | None = None
            if chart.program.keysounds:
                if silent_bank is None:
                    silent_bank = write_silent_keysound_bank(
                        workspace / "silent_keysounds.s3p", encoder=music_processor.encoder
                    )
                sampler_filename = f"general_sampler_{assignment.slot.suffix}.s3p"
                resources.append(
                    PackageResource(silent_bank, metadata.directory / sampler_filename)
                )
            conversion = apply_rendered_audio(
                chart.conversion,
                chart.source,
                chart.program,
                options=options,
                keysound_sample=SILENT_KEYSOUND_SAMPLE if sampler_filename is not None else 0,
            )
            rendered_charts.append(replace(chart, conversion=conversion))
            full = music_processor.process(
                MusicRequest(
                    rendered_music_resource(rendered, chart.binding.path),
                    workspace / metadata.music_filename(slot=assignment.slot),
                    audio_settings,
                )
            )
            resources.append(
                PackageResource(full.resource, metadata.directory / full.resource.path.name)
            )
            diagnostics.extend(
                replace(d, source_path=str(chart.binding.path))
                for d in (*conversion.report.diagnostics, *rendered.diagnostics, *full.diagnostics)
            )
            audio_reports.append(
                {
                    "slot": assignment.slot.value,
                    "file": full.resource.path.name,
                    "rendering": rendering_report(
                        rendered, chart.binding.path.relative_to(config.root).as_posix()
                    ),
                    "coverage": chart.program.coverage_paths,
                    "native_keysounds": {
                        "sample": SILENT_KEYSOUND_SAMPLE if sampler_filename is not None else 0,
                        "bank": sampler_filename,
                        "silent": True,
                    },
                    "source_volume": bgm.volume,
                    "offset_ms": int(bgm.offset),
                    **audio_measurements(full),
                }
            )
            jacket = jackets.get(chart.binding.path)
            if jacket is None:
                continue
            for size, label in (
                (JacketSize.SMALL, "small"),
                (JacketSize.STANDARD, "standard"),
                (JacketSize.LARGE, "big"),
                (JacketSize.SELECTOR, "selector"),
            ):
                filename = (
                    f"jk_{config.song_id:04}_{assignment.slot.number}_t.png"
                    if label == "selector"
                    else metadata.jacket_filename(assignment.slot, label)
                )
                path = (
                    PurePosixPath("graphics/s_jacket00_ifs") / filename
                    if label == "selector"
                    else metadata.directory / filename
                )
                result = jacket_processor.process(
                    JacketRequest(
                        jacket,
                        workspace / filename,
                        JacketSettings(size),
                    )
                )
                resources.append(PackageResource(result.resource, path))
                diagnostics.extend(result.diagnostics)
        diagnostics.append(
            Diagnostic(
                "PACKAGE_MEDIA_CONVERTED",
                Severity.INFO,
                Stage.PACKAGE,
                "Music and preview files were produced, along with any supplied jackets.",
                "package",
            )
        )
        diagnostics = [_portable_diagnostic(d, config.root) for d in diagnostics]
        package = SdvxPackage(
            tuple(
                PackageChart(
                    chart.binding.path,
                    str(metadata.directory / metadata.chart_filename(assignment.slot)),
                    chart.conversion.chart,
                )
                for chart, assignment in zip(rendered_charts, assignments, strict=True)
            ),
            metadata,
            tuple(resources),
            tuple(diagnostics),
        )
        report: dict[str, JsonValue] = {
            "song_id": config.song_id,
            "name": config.name,
            "profile": profile.name,
            "options": options.to_dict(),
            "charts": tuple(
                {
                    "source": chart.binding.path.relative_to(config.root).as_posix(),
                    "slot": chart.binding.slot,
                    "conversion": chart.conversion.report.to_dict(),
                }
                for chart in rendered_charts
            ),
            "music": {
                "target_lufs": config.target_lufs,
                "true_peak_dbtp": config.true_peak_dbtp,
                "charts": tuple(audio_reports),
                "preview": {
                    "file": preview.resource.path.name,
                    "reference": "original_full_track",
                    "start_ms": int(bgm.preview_offset),
                    "duration_ms": int(bgm.preview_duration),
                    **audio_measurements(preview),
                },
            },
            "diagnostics": tuple(d.to_dict() for d in diagnostics),
        }
        return LayeredFsPackageWriter(report=report).write(package, destination=destination)
