# ksm2sdvx

KSM-to-SDVX conversion components. Python 3.14 or later is required.
After completing the source setup below:

```text
uv sync
uv run ksm2sdvx chart chart.kson -o output/chart.vox
uv run ksm2sdvx audio music.ogg -o output/music.s3v
uv run ksm2sdvx audio --chart song/hard.kson -o output/hard.s3v
uv run ksm2sdvx jacket jacket.png --size 300 -o output/jacket.png
uv run ksm2sdvx inspect song/easy.kson song/hard.kson --root song
uv run ksm2sdvx package package.toml --game-data reference/data
```

## Development

Windows audio builds require MSVC with the C++ desktop tools and CMake 3.26 or
later. Run the commands from an x64 developer terminal. Source builds initialize only these
upstream submodules:

```text
git submodule update --init external/ksm-v2
git -C external/ksm-v2 submodule update --init ksmaudio kson
```

```text
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv run pytest --cov
uv build
```

Native DSP tests use generated audio:

```text
cmake -S . -B build/native -DBUILD_TESTING=ON
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
```

Related project:

- [vox2ksh](https://github.com/whiteou7/vox2ksh)
- [ksm-chart-format](https://github.com/kshootmania/ksm-chart-format)
- [ksm-v2](https://github.com/kshootmania/ksm-v2.git)
- [ifs_layeredfs](https://github.com/mon/ifs_layeredfs)
