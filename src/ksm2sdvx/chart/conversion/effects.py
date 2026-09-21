"""Chart feature accounting and effect support diagnostics."""

from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.kson.model import KsonChart
from ksm2sdvx.common.diagnostics import FeatureStatus


def report_unconverted(chart: KsonChart, report: ReportBuilder) -> None:
    report.record(
        "metadata",
        FeatureStatus.DEFERRED,
        "/meta",
        code="PACKAGE_METADATA",
        message="Metadata is preserved as package data; VOX chart text has no metadata mapping.",
    )
    if chart.assets or chart.audio.bgm:
        report.record(
            "assets",
            FeatureStatus.DEFERRED,
            "/audio",
            code="PACKAGE_ASSETS",
            message="Asset references and BGM settings are preserved; asset processing is deferred.",
        )
    for name, group in (("fx", chart.audio.fx), ("laser", chart.audio.laser)):
        base = f"/audio/audio_effect/{name}"
        for i, _ in enumerate(group.definitions):
            report.record(
                "audio_effect",
                FeatureStatus.UNSUPPORTED,
                f"{base}/def/{i}",
                code="UNSUPPORTED_EFFECT_DEFINITION",
                message="Effect definition preserved but not translated.",
            )
        for event in (*group.changes, *group.invocations):
            report.record(
                "audio_effect",
                FeatureStatus.UNSUPPORTED,
                event.path,
                code="UNSUPPORTED_EFFECT_EVENT",
                message="Effect event preserved but not translated.",
                pulse=event.pulse,
            )
        for field in group.retained:
            report.record(
                "audio_effect",
                FeatureStatus.UNSUPPORTED,
                field.path,
                code="UNSUPPORTED_EFFECT_PARAMETER",
                message="Effect parameter preserved but not translated.",
            )
        if group.peaking_filter_delay:
            report.record(
                "audio_effect",
                FeatureStatus.UNSUPPORTED,
                base + "/peaking_filter_delay",
                code="UNSUPPORTED_EFFECT_PARAMETER",
                message="Laser filter delay requires audio rendering.",
            )
        for event in group.filter_gain:
            report.record(
                "audio_effect",
                FeatureStatus.UNSUPPORTED,
                event.path,
                code="UNSUPPORTED_EFFECT_PARAMETER",
                message="Laser filter gain requires audio rendering.",
                pulse=event.pulse,
            )
    for chip in chart.audio.key_sound.chips:
        report.record(
            "keysound",
            FeatureStatus.UNSUPPORTED,
            chip.path,
            code="UNSUPPORTED_KEYSOUND",
            message="Chip keysound requires audio rendering.",
            pulse=chip.pulse,
        )
    for field in chart.audio.key_sound.laser:
        report.record(
            "keysound",
            FeatureStatus.UNSUPPORTED,
            field.path,
            code="UNSUPPORTED_KEYSOUND",
            message="Keysound configuration preserved but not converted.",
        )
    if chart.audio.bgm and chart.audio.bgm.legacy_filenames:
        report.record(
            "audio_effect",
            FeatureStatus.UNSUPPORTED,
            "/audio/bgm/legacy/fp_filenames",
            code="UNSUPPORTED_LEGACY_AUDIO",
            message="Legacy alternate BGM routing is not rendered.",
        )
    for field in chart.retained:
        if field.path in ("/editor", "/compat"):
            report.record(
                field.path[1:],
                FeatureStatus.DEFERRED,
                field.path,
                code="RETAINED_SOURCE_DATA",
                message="Source annotations retained as package data.",
            )
        elif field.value:
            report.record(
                field.path[1:],
                FeatureStatus.UNSUPPORTED,
                field.path,
                code="UNSUPPORTED_SOURCE_FEATURE",
                message="Source feature is retained but has no VOX mapping.",
            )
    for field in chart.extensions:
        report.record(
            "extension",
            FeatureStatus.UNSUPPORTED,
            field.path,
            code="UNKNOWN_EXTENSION",
            message="Unknown source extension retained without interpretation.",
        )
