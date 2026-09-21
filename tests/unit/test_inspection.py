import json
from pathlib import Path

import pytest
from tests.conftest import document

from ksm2sdvx.chart import DEFAULT_PROFILE, ConversionOptions
from ksm2sdvx.common.diagnostics import Stage
from ksm2sdvx.common.types import json_ready
from ksm2sdvx.pipeline import SourcePackage, inspect_package
from ksm2sdvx.pipeline.report import inspection_to_dict
from ksm2sdvx.resources.errors import AssetError


def write_source(path: Path, **overrides: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document(**overrides), encoding="utf-8")
    return path


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_shared_assets_offsets_and_read_only(tmp_path: Path) -> None:
    (tmp_path / "music.ogg").write_bytes(b"fixture")
    charts = tuple(
        write_source(tmp_path / name, audio={"bgm": {"filename": "music.ogg", "offset": offset}})
        for name, offset in (("easy.kson", -120), ("hard.kson", 240))
    )
    before = snapshot(tmp_path)
    inspection = inspect_package(
        SourcePackage(tmp_path, charts), options=ConversionOptions(), profile=DEFAULT_PROFILE
    )
    assert inspection.valid and len(inspection.assets) == 1
    assert len(inspection.assets[0].uses) == 2
    offsets = [
        chart.source.audio.bgm.offset for chart in inspection.charts if chart.source.audio.bgm
    ]
    assert offsets == [-120, 240]
    assert snapshot(tmp_path) == before
    encoded = json.dumps(json_ready(inspection_to_dict(inspection)), allow_nan=False)
    assert '"first": {"kind": 0' in encoded
    assert '"laser_effects": [{"kind": 1' in encoded
    assert inspection.charts[0].conversion.chart.format_version == 13
    payload = inspection_to_dict(inspection)
    assert set(payload) == {"schema_version", "valid", "root", "charts", "assets", "diagnostics"}
    assert payload["schema_version"] == 2
    assert {use.source for use in inspection.assets[0].uses} == set(charts)


def test_presets_keysounds_and_nested_assets(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "custom.wav").write_bytes(b"fixture")
    text = document(
        audio={
            "key_sound": {"fx": {"chip_event": {"clap": [[0], []], "../custom.wav": [[240], []]}}}
        },
        bg={"filename": "desert"},
    )
    # Add a jacket preset without compromising the canonical required metadata.
    text = text.replace('"disp_bpm": "120"', '"disp_bpm": "120", "jacket_filename": "nowprinting1"')
    chart = tmp_path / "sub/chart.kson"
    chart.write_text(text, encoding="utf-8")
    inspection = inspect_package(
        SourcePackage(tmp_path, (chart,)), options=ConversionOptions(), profile=DEFAULT_PROFILE
    )
    assert inspection.valid
    assert {a.name for a in inspection.assets} == {"../custom.wav", "nowprinting1"}
    assert sum(a.preset for a in inspection.assets) == 1
    assert (
        next(a for a in inspection.assets if not a.preset).resolved_path == tmp_path / "custom.wav"
    )


@pytest.mark.parametrize(
    "filename,code",
    [
        ("missing.ogg", "MISSING_ASSET"),
        ("../escape.ogg", "INVALID_ASSET_PATH"),
        ("C:/outside.ogg", "INVALID_ASSET_PATH"),
        ("/outside.ogg", "INVALID_ASSET_PATH"),
        ("music.ogg:stream", "INVALID_ASSET_PATH"),
    ],
)
def test_invalid_asset_inspections(tmp_path: Path, filename: str, code: str) -> None:
    chart = write_source(tmp_path / "chart.kson", audio={"bgm": {"filename": filename}})
    before = snapshot(tmp_path)
    inspection = inspect_package(
        SourcePackage(tmp_path, (chart,)), options=ConversionOptions(), profile=DEFAULT_PROFILE
    )
    assert not inspection.valid
    assert code in {d.code for d in inspection.diagnostics}
    assert all(d.stage is Stage.INSPECT for d in inspection.diagnostics if d.code == code)
    assert snapshot(tmp_path) == before


def test_chart_collisions_and_containment(tmp_path: Path) -> None:
    first = write_source(tmp_path / "a/chart.kson")
    second = write_source(tmp_path / "b/CHART.kson")
    with pytest.raises(AssetError, match="Conflicting"):
        inspect_package(
            SourcePackage(tmp_path, (first, second)),
            options=ConversionOptions(),
            profile=DEFAULT_PROFILE,
        )
    with pytest.raises(AssetError, match="escapes"):
        inspect_package(
            SourcePackage(first.parent, (second,)),
            options=ConversionOptions(),
            profile=DEFAULT_PROFILE,
        )


def test_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    outside = tmp_path / "outside.ogg"
    outside.write_bytes(b"outside")
    try:
        (root / "music.ogg").symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit unprivileged symlinks")
    chart = write_source(root / "chart.kson", audio={"bgm": {"filename": "music.ogg"}})
    inspection = inspect_package(
        SourcePackage(root, (chart,)), options=ConversionOptions(), profile=DEFAULT_PROFILE
    )
    assert not inspection.valid
