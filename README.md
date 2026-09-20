# ksm2sdvx

KSM-to-SDVX conversion components for charts, music, jacket artwork, metadata,
and package output. Python 3.14 or later is required.

```text
uv sync
uv run ksm2sdvx chart chart.kson -o output/chart.vox
uv run ksm2sdvx inspect song/easy.kson song/hard.kson --root song
```

## Development

```text
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv run pytest --cov
uv build
```

See [architecture](docs/architecture.md) and [compatibility](docs/compatibility.md).

Related project: 
- [vox2ksh](https://github.com/whiteou7/vox2ksh)
- [ksm-chart-format](https://github.com/kshootmania/ksm-chart-format)
- [ksm-v2](https://github.com/kshootmania/ksm-v2.git)