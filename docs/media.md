# Audio and jacket commands

Use `audio` to create one S3V file and `jacket` to create one square PNG. These
commands take files directly and do not read a package TOML file. Package creation
uses the same processors when building a complete song.

Both commands require FFmpeg; jacket processing also requires FFprobe. Audio
encoding requires Windows with the Windows Media Format runtime. See the
[command reference](cli.md) for chart, inspection, and package commands.

## Audio

```text
uv run ksm2sdvx audio music.ogg -o output/music.s3v
uv run ksm2sdvx audio music.ogg --target-lufs -11 --offset-ms 120
uv run ksm2sdvx audio music.ogg --preview-start-ms 30000 --preview-duration-ms 15000
uv run ksm2sdvx audio --chart song/hard.kson --strict
```

Output is ASF with WMA Professional audio and a required 32-byte `S3V0` footer,
stereo at 44.1 kHz and approximately 384 kb/s. The default path is
`output/<stem>.s3v`; a preview defaults to `output/<stem>_pre.s3v`.

| Argument or option | Default | Behavior and constraints |
| --- | --- | --- |
| `SOURCE` | Required without `--chart` | Audio file decodable by FFmpeg |
| `--chart PATH` | None | Render effects and keysounds from a KSON chart instead of supplying `SOURCE` |
| `--strict` | Off | With `--chart`, reject omitted audio features |
| `-o PATH`, `--output PATH` | Path above | Select the `.s3v` file |
| `--target-lufs NUMBER` | `-11` | Integrated loudness target, finite number from −70 to 0 LUFS |
| `--true-peak-dbtp NUMBER` | `-1` | Peak ceiling before encoding, finite number from −20 to 0 dBTP |
| `--source-volume NUMBER` | `1` | Positive, finite amplitude multiplier applied to the loudness target |
| `--offset-ms INTEGER` | `0` | Signed 32-bit milliseconds; positive trims the start, negative pads silence |
| `--preview-start-ms INTEGER` | No preview | Start in the original audio, 0–2147483647 ms |
| `--preview-duration-ms INTEGER` | No preview | Duration, 1–2147483647 ms; supply both preview arguments and leave offset at 0 |
| `--gain-db NUMBER` | Calculated | Explicit finite constant gain, still checked against the measured peak ceiling |
| `--ffmpeg EXECUTABLE` | `ffmpeg` | Select the FFmpeg executable |
| `-h`, `--help` | — | Show audio command help |

### Loudness and previews

Normalization applies a constant volume gain limited by the available peak
headroom. The command prints the applied gain and measured output loudness when
available. Lossy encoding can raise the decoded peak; any overshoot is reported.
An independent preview uses its own measured loudness unless `--gain-db` is
supplied. Package creation normalizes each rendered difficulty independently;
its preview uses the original full-track loudness and the preview's peak headroom.
An explicit gain that exceeds peak headroom fails; it is not silently reduced.
Silent audio and intervals too short for the required measurement fail with an
audio error. Supplying a gain for a short preview requires only a peak measurement.

### Chart audio

`--chart` reads the music reference, offset, relative volume, effect definitions,
automation, laser graphs and chip keysounds from KSON. Its output is
`output/<chart-stem>.s3v` plus an adjacent `.report.json`, unless `-o` selects a
different file. The report records rendered features, dependency versions,
normalization and omissions. Raw-audio offset, source-volume and preview options
cannot be combined with `--chart`.

The Windows x64 wheel contains the renderer, BASS runtime, and the `clap`,
`clap_impact`, `clap_punchy`, `snare`, and `snare_lo` presets. No KSM installation
or setup command is needed. Other sample and switch-audio files resolve relative
to the chart and must remain inside its directory. Package conversion instead
uses the TOML directory as its containment boundary.

### What chart rendering changes

The renderer uses KSM's music effect and compressor chain, then mixes chip
keysounds. BGM volume controls its level relative to keysounds. The completed mix
saturates at the signed PCM output range before receiving one constant
normalization gain. Reports identify the processing profile and count saturated
samples. Effects follow the authored chart regardless of player input.
Raw-audio conversion and original-audio previews do not use this compressor chain.
Arcade slam feedback is retained rather than baked into the audio. Custom slam
sounds, legacy alternate-BGM routing and unknown audio features are diagnosed;
`--strict` rejects their omission. Missing resources and invalid parameters fail
in either mode. Chart audio rendering does not write a VOX file; `package`
produces the matching chart with native audio effects disabled.

## Jacket

```text
uv run ksm2sdvx jacket jacket.png
uv run ksm2sdvx jacket jacket.png --size 128 -o output/selector.png
```

Output is an 8-bit RGB PNG at `output/<stem>_<size>.png`, unless `-o` selects
another file. One invocation writes one size; package creation writes all four.

| Argument or option | Default | Behavior and constraints |
| --- | --- | --- |
| `SOURCE` | Required | Image file decodable by FFmpeg; the first frame is used |
| `-o PATH`, `--output PATH` | Path above | Select a `.png` file |
| `--size INTEGER` | `300` | 108 (small), 128 (selector), 300 (standard), or 676 (large) pixels per side |
| `--ffmpeg EXECUTABLE` | `ffmpeg` | Select the FFmpeg executable |
| `--ffprobe EXECUTABLE` | `ffprobe` | Select the FFprobe executable |
| `-h`, `--help` | — | Show jacket command help |

Images always use contain: the entire image keeps its aspect ratio, with black
margins filling the square. Transparent pixels composite onto black. Use
`--ffmpeg` and `--ffprobe` to select executables.

Jacket credits belong to package metadata: they come from KSON or the
`[jacket].author` and `[charts.jacket].author` overrides in package configuration.

Both commands resolve relative paths from the working directory. They replace
an existing output only after successful processing and
validation. They reject overwriting the source. Exit codes are 0 for success,
1 for input or processing failures, and 2 for argument errors.
