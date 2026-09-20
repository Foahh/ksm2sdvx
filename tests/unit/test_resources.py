from pathlib import Path

from ksm2sdvx.common.diagnostics import Stage
from ksm2sdvx.resources import ResourceInput, ResourceReference, discover_resources


def test_resource_discovery_accepts_non_chart_owners(tmp_path: Path) -> None:
    owner = tmp_path / "song.manifest"
    owner.write_text("resource manifest", encoding="utf-8")
    (tmp_path / "shared.bin").write_bytes(b"resource")
    inputs = (
        ResourceInput(owner, ResourceReference("shared.bin", "music", "/music")),
        ResourceInput(owner, ResourceReference("./shared.bin", "preview", "/preview")),
        ResourceInput(owner, ResourceReference("builtin", "jacket", "/jacket", preset=True)),
        ResourceInput(owner, ResourceReference("missing.bin", "background", "/background")),
    )
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    inventory = discover_resources(inputs, root=tmp_path)
    assert len(inventory.assets) == 3
    assert inventory.assets[0].resolved_path == tmp_path / "shared.bin"
    assert [use.role for use in inventory.assets[0].uses] == ["music", "preview"]
    assert inventory.assets[1].preset and inventory.assets[1].resolved_path is None
    assert not inventory.assets[2].exists
    assert len(inventory.diagnostics) == 1
    assert inventory.diagnostics[0].stage is Stage.INSPECT
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before
