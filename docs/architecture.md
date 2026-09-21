# Architecture

`ksm2sdvx` is one Python 3.14+ package with one command. Chart conversion,
media processing, metadata conversion, and resource discovery have separate
modules. The package pipeline combines them to produce a mod directory.

The dependency direction is simple: the pipeline uses components, but components
do not import the pipeline. Shared code does not import components. CLI modules
handle arguments and display results; conversion code does not import the CLI.

## Find the code

Use this map to locate the owner of a behavior:

```text
src/ksm2sdvx/
  chart/
    kson/           source chart models, parsing, validation
    vox/            target chart models, validation, serialization
    conversion/     timing, buttons, lasers, camera, feature accounting
    geometry/       curve evaluation, fitting, smoothing
    audio.py        pure chart-audio compilation and rendered-chart adjustments
    audio_model.py  immutable effect, laser and sample instructions
    audio_timing.py exact pulse-to-frame timing and effect triggers
    application.py  source loading, conversion, staged chart/report writing
    cli.py          chart arguments and presentation
    types.py        pulses, durations, measures, ticks
    errors.py       chart decoding, validation, conversion failures
  music/
    models.py       audio settings, measurements, requests and results
    interfaces.py   MusicProcessor and S3vEncoder protocols
    processor.py    FFmpeg analysis, timing, constant gain and verification
    render_models.py neutral render requests, results and renderer protocol
    renderer.py     bundled native helper and PCM preparation
    _windows.py     Windows WMA Professional encoding
    application.py  standalone audio file conversion
    cli.py          audio arguments and presentation
    errors.py       audio processing failures
  jacket/
    models.py       sizes, requests and results
    interfaces.py   JacketProcessor protocol
    processor.py    FFmpeg image processing and PNG validation
    application.py  standalone jacket file conversion
    cli.py          jacket arguments and presentation
    errors.py       image processing failures
  metadata/
    models.py       source metadata, slot assignments and SDVX metadata
    interfaces.py   MetadataConverter protocol
    database.py     immutable XML records and reference database loading
    converter.py    new-song metadata conversion and XML serialization
    errors.py       metadata validation and encoding failures
  resources/
    models.py       neutral references, uses, inventory and processed files
    discovery.py    resolution, containment and deduplication
    errors.py       resource resolution failures
  pipeline/
    config.py       TOML loading and package configuration models
    models.py       inspection, composed package and output records
    inspection.py  read-only chart conversion and resource inventory
    report.py      inspection JSON serialization
    build.py       chart, metadata, music and jacket composition
    audio.py       chart audio resource binding, rendering and reports
    interfaces.py  PackageWriter protocol
    writer.py      staged LayeredFS directory output
    errors.py      package configuration and composition failures
  common/
    diagnostics.py diagnostic records, stages and severity
    errors.py      Ksm2SdvxError and general output failures
    types.py       milliseconds and immutable JSON values
    cli.py         diagnostic presentation shared by CLI adapters
  cli.py            command dispatch and expected-error presentation
  __main__.py       python -m ksm2sdvx
  py.typed          installed typing marker
```

All packages have ordinary `__init__.py` files. Tests live outside `src/`.
The C++ renderer lives under `native/`; `external/ksm-v2` pins its upstream
audio implementation, dependencies and sample assets. The CMake build selects
only audio inputs and does not build the game.

Public APIs live in their owning subpackages. The package root imports no
components. Models use frozen, slotted dataclasses and tuple collections;
settings and target metadata types are supplied by the caller. Imports perform
no application filesystem work and initialize no media processors.

## What each component does

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Chart | KSON parsing, conversion, VOX serialization, chart file output | Implemented |
| Resources | Resolve references and inventory shared files and presets | Implemented |
| Package inspection | Validate selected charts and inventory their resources | Implemented, read-only |
| Music | Render chart effects and keysounds, normalize mixes, encode music and previews | Bundled ksmaudio renderer, FFmpeg and Windows WMA Professional; typed renderer and processor interfaces |
| Jacket | Produce standard, small, large and selector jackets | FFmpeg implementation; `JacketProcessor` protocol |
| Metadata | Produce a new song entry from source values and target defaults | Shift-JIS XML adapter; `MetadataConverter` protocol |
| Package output | Write composed charts, metadata, and processed resources | Staged LayeredFS directory writer; `PackageWriter` protocol |

The installed command exposes `chart`, `audio`, `jacket`, `inspect` and `package`.
The package command adds one explicitly grouped song. It requires FFmpeg,
FFprobe and the Windows Media Format runtime; chart conversion, inspection and
jacket processing remain portable. See the [command reference](cli.md) and
[package creation](package.md) for configuration and output.

`music.application.convert_audio_file` and `jacket.application.convert_jacket_file`
accept standalone source and output paths. Their component CLI modules handle
arguments and presentation, using the same processors as package creation.
See [media commands](media.md) for options and defaults.

Media processing, metadata conversion and package writing have concrete
implementations behind their protocols. FX translation and automatic score/radar
calculation remain unsupported and produce diagnostics.

## Chart conversion

The chart path has four steps: parse KSON, validate the source, convert to a VOX
model, then validate and serialize that model. File loading and writing sit at
the application boundary. This makes each step testable on its own.

`parse_kson(text)` returns `ParsedKson(chart, diagnostics)`; `load_kson(path)` adds
file loading and source information. Compact wire representations are normalized
once. Source validation also runs before conversion, so direct model construction
does not bypass semantic checks. Unknown optional values retain their JSON
pointers. Metadata, audio settings, effect definitions, string-valued effect
parameters, and invocation order remain in the source model.

`convert_chart(chart, *, options, profile)` returns `ConversionResult(chart, report)`.
The converter builds a rational meter timeline, converts notes, samples lasers,
associates spins, converts camera events, accounts for unsupported features,
computes the end position, and validates the target. Distinct nominal types keep
source pulses, source durations, measure indices, and VOX ticks separate.

`serialize_vox(chart)` validates and serializes target data with explicit section
order, simultaneous-event order, numeric precision, and LF endings. It does not
interpret KSON or make conversion decisions. Target models represent VOX sections
independently of which features the converter emits.

Original laser tracks contain source control nodes and jump endpoints; playback
tracks additionally contain sampled points. Initialization precedes camera value
rows. End position includes notes, camera and spin durations, BPM changes, meter
changes, and tilt modes. Conversion behavior is detailed in
[compatibility](compatibility.md).

`chart.application.convert_chart_file` combines loading, conversion, report
assembly, and file output. The pure chart API remains available independently.
Typed curve fitting utilities remain internal to `chart.geometry`, separate from
the forward chart conversion passes.

## Resources and inspection

`ResourceReference` describes a file or symbolic preset and its source location.
`discover_resources` accepts references with owning source files. It resolves
files relative to their owners, enforces package-root containment, distinguishes
presets, and deduplicates shared files. Every resource retains all its uses.
Resource discovery has no dependency on KSON models and does not open asset
contents.

`inspect_package(SourcePackage(root, charts), *, options, profile)` requires an
explicit root and chart list. Chart paths are resolved from the caller's working
directory. Song grouping is never inferred. Case-insensitive chart output-name
collisions are errors on every platform; resolved symlinks participate in
containment checks.

`PackageInspection` contains source and converted chart models, resource records,
and diagnostics. Per-chart metadata, audio offsets, and preview settings are
preserved. Its `valid` property concerns chart conversion and resource references;
it does not certify media encoding or complete-package output.

`inspection_to_dict` emits schema version 2 with `schema_version`, `valid`, `root`,
`charts`, `assets`, and `diagnostics`. Effect type identifiers remain explicit in
the serialized models. Chart conversion reports use their separate version 1
schema. Inspection never creates output directories or writes files.

## Package processing

Package creation combines chart conversion with media rendering, metadata, and
file output. Each component exposes a typed request and result; the pipeline
decides when to call it and where to put its output.

`MusicRequest[SettingsT]` and `JacketRequest[SettingsT]` carry a discovered source
resource, explicit destination, and typed settings. Their processors return a
`ProcessedResource` and diagnostics after producing an output, or raise an
expected error. Processed references retain the source uses they satisfy.
The generic contracts allow other implementations. Concrete settings specify
the WMA Professional audio format and supported RGB PNG jacket sizes.

`PackageMetadata` contains a separate `ChartMetadata` record for each chart,
including audio offsets and preview timing. The pipeline does not select
song-wide values implicitly. `MetadataConverter[SettingsT, TargetT]` returns a
typed target payload and diagnostics. Target metadata schemas belong to concrete
adapters.

`SdvxPackage[MetadataT]` composes named VOX charts, target metadata, and
`PackageResource` records assigning processed files to relative output paths.
`PackageWriter[MetadataT]` accepts this model and an explicit destination,
returning the files actually written and diagnostics.

`build_package` loads the selected charts, validates resource references, converts
metadata, and processes music and jackets in a temporary workspace. Charts must
share their music file, offset, source volume and preview timing. Explicit target
slots determine output names.

### Configuration and metadata

`PackageConfig` contains explicit chart bindings plus music, metadata and jacket
settings. Its `name` supplies the mod directory name, resource filename suffix
and target database `ascii` value. Its source root is derived from the TOML file's
directory; chart and jacket override paths resolve from that directory.
`JacketConfig` is shared by song-wide and per-chart overrides, with each field
resolved independently. The TOML configuration has no schema-version
selector. CLI conversion options remain separate `ConversionOptions` inputs.
The [complete configuration reference](package.md#complete-configuration-reference)
documents all accepted fields and their defaults.

`SdvxMetadataConverter` builds a new ID from chart levels, authors, title, artist,
BPM and resource names. It checks the reference database for ID collisions,
disables unselected slots, and emits explicit target defaults. Jacket credits
come from KSON unless shared or per-chart jacket settings override the author.
`ChartRadar` preserves six optional per-chart values; song and chart database
controls accept explicit overrides validated against their XML integer types.
Score and radar calculation are not implemented: unspecified radar values and
maximum EX scores are zero, with diagnostics. The serializer writes a Shift-JIS
`music_db.merged.xml` fragment and rejects text that cannot be encoded.

### Audio rendering and encoding

`compile_chart_audio` produces immutable audio instructions without file access.
`AudioRenderRequest` binds those instructions to resolved music and sample files;
`AudioRenderer` returns a completed PCM resource and a render receipt.
`NativeAudioRenderer` prepares stereo 44.1 kHz floating-point inputs, invokes the
bundled helper, and validates its response before publishing the PCM file.
The helper uses ksmaudio's music stream and compressor chain from the pinned KSM
submodule, with effects scheduled on an offline sample clock. Chip samples are
mixed afterward; the final mix saturates at the signed PCM range before loudness
measurement. Render receipts record the processing profile and saturated sample
count. Presets and BASS libraries ship beside the executable.

The package pipeline renders and normalizes each difficulty separately, then
disables native chart effects only after the render succeeds. Exact source
feature coverage resolves audio omissions before strict policy is enforced.
Standalone chart conversion cannot claim that rendering has happened.

`FfmpegMusicProcessor.process_preview` selects constant gain from the original
full-track loudness and preview peak. Gameplay mixes each receive their own
normalization, with a default target of −11 LUFS. Standalone `process` converts
one requested interval. The Windows
encoder produces WMA Professional audio, closes the ASF payload, then appends
and validates the required S3V footer. Plain ASF files renamed to `.s3v` are not
valid game output. There is no alternate-codec fallback.
`FfmpegJacketProcessor` produces RGB PNGs at the four supported sizes, always
preserving the full image's aspect ratio with black margins (contain).

### Publishing files

`LayeredFsPackageWriter` checks relative paths and collisions, stages charts,
processed assets, metadata and a report, then publishes a new mod directory.
The caller must choose an unused destination. Source assets and the reference
database are never modified. Concurrent writers must use distinct destinations.

FX event translation belongs to chart conversion. Audio rendering belongs to the
music component. Source effect information remains available for both boundaries;
the current chart converter diagnoses untranslated audible behavior.

## Errors and output

Expected errors derive from `Ksm2SdvxError`. Chart, music, jacket, metadata,
resource and package errors belong to their components; output errors are shared.
Unexpected programming errors are not caught as ordinary input failures.
Diagnostics carry stable codes, severity, stage, feature, source location, and
optional integer pulse. Shared diagnostics do not depend on chart-specific types.

Chart output stages VOX and report files before replacing either. Each replacement
is atomic; the pair is not a filesystem transaction. Failure of the second
replacement is reported and can leave a new chart beside the previous report.

## Verification

Synthetic golden fixtures and typed-model tests cover chart behavior. Inspection
tests check resource handling and filesystem contents before and after execution.
CLI integration tests cover command options, exit codes, and file output. Local
verification includes lint, formatting, strict type checking, tests, and package
builds. Media tests use generated images and audio, with real FFmpeg processing
when available. WMA Professional encoding tests require Windows; tests never
depend on an installed game or private reference assets.
