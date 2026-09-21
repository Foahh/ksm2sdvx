# ksm2sdvx

Convert KSON charts to VOX v13 and build song packages for
[ifs_layeredfs](https://github.com/mon/ifs_layeredfs). The tool also converts
individual audio and jacket files. It requires Python 3.14 or later and uses
[`uv`](https://docs.astral.sh/uv/) to run from source.

## Start here

On Windows, source builds need MSVC with the C++ desktop tools, CMake 3.26 or
later, and an x64 developer terminal. Initialize the pinned upstream audio code,
install the project, then convert one chart:

```sh
git submodule update --init external/ksm-v2
git -C external/ksm-v2 submodule update --init ksmaudio kson
uv sync
uv run ksm2sdvx chart song/hard.kson -o output/hard.vox
```

This writes `output/hard.vox` and `output/hard.report.json`. A chart conversion
does not process its music or artwork. To build a complete song package, start
with [examples/package.toml](examples/package.toml), copy it into your song
directory, and run:

```sh
uv run ksm2sdvx package song/package.toml --game-data reference/data
```

Package creation needs Windows with the Windows Media Format runtime, plus
FFmpeg and FFprobe. See [package creation](docs/package.md) for setup, configuration, and output.

## Other commands

| Task | Example | Details |
| --- | --- | --- |
| Inspect charts and referenced files without writing output | `uv run ksm2sdvx inspect song/easy.kson song/hard.kson --root song` | [Command reference](docs/cli.md#package-inspection) |
| Convert one audio file | `uv run ksm2sdvx audio music.ogg -o output/music.s3v` | [Audio options](docs/media.md#audio) |
| Render a chart's effects and keysounds into audio | `uv run ksm2sdvx audio --chart song/hard.kson -o output/hard.s3v` | [Chart audio](docs/media.md#chart-audio) |
| Resize artwork | `uv run ksm2sdvx jacket jacket.png --size 300 -o output/jacket.png` | [Jacket options](docs/media.md#jacket) |

Run `uv run ksm2sdvx --help` for command help. The [command reference](docs/cli.md)
explains output paths, shared options, exit codes, and reports.

## Development

Run the checks and build:

```sh
uv sync
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pyright
uv run pytest
uv build
```

Native tests:

```sh
cmake -S . -B build/native -DBUILD_TESTING=ON
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
```

Related projects:

- [vox2ksh](https://github.com/whiteou7/vox2ksh)
- [ksm-chart-format](https://github.com/kshootmania/ksm-chart-format)
- [ksm-v2](https://github.com/kshootmania/ksm-v2.git)
- [ifs_layeredfs](https://github.com/mon/ifs_layeredfs)
