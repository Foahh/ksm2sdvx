# Command reference

One installed command exposes all implemented components:

```text
uv run ksm2sdvx chart SOURCE [-o OUTPUT] [conversion options]
uv run ksm2sdvx audio SOURCE [-o OUTPUT] [audio options]
uv run ksm2sdvx audio --chart CHART.kson [-o OUTPUT] [--strict] [audio options]
uv run ksm2sdvx jacket SOURCE [-o OUTPUT] [jacket options]
uv run ksm2sdvx inspect SOURCE... --root ROOT [conversion options]
uv run ksm2sdvx package MANIFEST --game-data DATA [-o OUTPUT] [package options]
```

`uv run python -m ksm2sdvx` accepts the same commands and arguments. Use
`uv run ksm2sdvx --help` or append `--help` to any subcommand for its options.
Command-line paths resolve relative to the working directory. The package
configuration resolves chart and jacket paths from its own directory, which is
also the source root. See its [path rules](package.md#complete-configuration-reference).

## Chart conversion

```text
uv run ksm2sdvx chart song/hard.kson
uv run ksm2sdvx chart song/hard.kson -o exports/hard.vox --strict
```

`SOURCE` is one KSON file. The command parses and validates it, converts the chart,
then writes VOX v13 and an adjacent JSON report. Output defaults to
`output/<stem>.vox` and `output/<stem>.report.json`. `-o` / `--output` must name a
`.vox` file; the report uses the same stem with `.report.json`.

This command produces chart text. It records metadata and media references as
deferred package data and does not read or process those media files. Use
`package` to produce a complete mod directory from supported chart and media data.
See [conversion compatibility](compatibility.md) for supported chart features.

## Package inspection

```text
uv run ksm2sdvx inspect song/easy.kson song/hard.kson --root song
```

Supply one or more explicit chart paths and the source root. Paths are resolved
from the working directory; `--root` is the containment boundary, not a prefix
prepended to chart arguments. The command loads and converts charts in memory,
preserves their individual metadata and audio offsets, inventories references,
and prints JSON to stdout. It writes no files and does not infer song grouping.

Inspection reports missing files, references outside the root and conflicting
chart output names. Its `valid` flag concerns charts and resource references;
it does not certify audio/image processing or complete package output.

## Shared chart conversion options

These options apply to `chart`, `inspect` and `package`:

| Option | Default | Meaning |
| --- | --- | --- |
| `--strict` | Off | Reject omitted source features; supported approximations remain allowed |
| `--curve-step PULSES` | `15` | Positive integer divisible by 5; laser/tilt curve and scroll-speed ramp sampling interval, and maximum moving zoom span |

Camera conversion uses a fixed joint zoom projection and angular tilt mapping.
See [camera behavior and limits](compatibility.md#chart-conversion).

Malformed input, unrepresentable timing and unsupported zoom projections fail in either mode. Media and
metadata references do not fail strict chart conversion merely because they are
absent from chart text. Package creation additionally checks unmapped metadata
and resources, as described in its [conversion limits](package.md#conversion-limits-and-failures).

## Audio, jacket and package output

| Command | Default output | Options |
| --- | --- | --- |
| `audio` | `output/<stem>.s3v`, or `output/<stem>_pre.s3v` for a preview | [Audio options and −11 LUFS normalization](media.md#audio) |
| `jacket` | `output/<stem>_<size>.png` | [Jacket sizes and image processing](media.md#jacket) |
| `package` | `output/data_mods/<name>/` | [Package options and exhaustive TOML reference](package.md) |

Standalone chart and media commands may replace their output files after staging.
Package creation requires a new destination and publishes the directory after
processing succeeds. Source files and reference game data are never overwritten.

## Exit codes and reports

Success returns 0, expected input or processing failures return 1, and argument
errors return 2. A completed inspection with `valid: false` returns 1. Diagnostics
from output-producing commands appear on stderr; unexpected programming errors
are not disguised as input failures.

Chart reports use schema version 1, inspection JSON uses version 2, and package
reports use version 1. These versions describe generated JSON, not the TOML
configuration. Chart audio rendering (`audio --chart`) writes an adjacent
version 1 report. Raw audio and jacket commands print results and diagnostics
without writing an adjacent JSON report.
