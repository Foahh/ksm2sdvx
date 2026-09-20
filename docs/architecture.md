# Architecture

`ksm2sdvx` is one installable project. Its components separate chart conversion,
media processing, metadata conversion, resource discovery, and package output.
The pipeline composes components. Components do not import the pipeline, and
shared modules do not import components. CLI modules handle arguments and
presentation; domain code never imports them.

```text
src/ksm2sdvx/
  chart/
    kson/           source chart models, parsing, validation
    vox/            target chart models, validation, serialization
    conversion/     timing, buttons, lasers, camera, feature accounting
    geometry/       curve evaluation, fitting, smoothing
    application.py  source loading, conversion, staged chart/report writing
    cli.py          chart arguments and presentation
    types.py        pulses, durations, measures, ticks
    errors.py       chart decoding, validation, conversion failures
  music/            audio processing models and interfaces
  jacket/           artwork processing models and interfaces
  metadata/         per-chart metadata and target conversion interface
  resources/        neutral references, discovery, containment, deduplication
  pipeline/         package inspection, composition models, writer interface
  common/           diagnostics, errors, milliseconds, immutable JSON values
  cli.py            command dispatch and expected-error presentation
```

Public APIs live in their owning subpackages. The package root imports no
components. Models use frozen, slotted dataclasses and tuple collections;
settings and target metadata types are supplied by the caller. Imports perform
no application filesystem work and initialize no media processors.

## Components and implementation status

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Chart | KSON parsing, conversion, VOX serialization, chart file output | Implemented |
| Resources | Resolve references and inventory shared files and presets | Implemented |
| Package inspection | Validate selected charts and inventory their resources | Implemented, read-only |
| Music | Produce audio files from explicit requests and settings | Models and `MusicProcessor` protocol |
| Jacket | Produce artwork files from explicit requests and settings | Models and `JacketProcessor` protocol |
| Metadata | Convert per-chart metadata into a target representation | Models and `MetadataConverter` protocol |
| Package output | Write composed charts, metadata, and processed resources | Models and `PackageWriter` protocol |

The installed command exposes `chart` and `inspect`. Interface-only components
have no command, registered implementation, or fallback that reports success.
No complete-package conversion coordinator is included.

## Chart boundary

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

## Processing and output contracts

`MusicRequest[SettingsT]` and `JacketRequest[SettingsT]` carry a discovered source
resource, explicit destination, and typed settings. Their processors return a
`ProcessedResource` and diagnostics after producing an output, or raise an
expected error. Processed references retain the source uses they satisfy.
Settings are generic; the contracts prescribe no codec or image dimensions.

`PackageMetadata` contains a separate `ChartMetadata` record for each chart,
including audio offsets and preview timing. There is no implicit selection of
song-wide values. `MetadataConverter[SettingsT, TargetT]` returns a typed target
payload and diagnostics. Target metadata schemas belong to concrete adapters.

`SdvxPackage[MetadataT]` composes named VOX charts, target metadata, and processed
resource references. `PackageWriter[MetadataT]` accepts this model and an explicit
destination, returning the files actually written and diagnostics. These models
and protocols perform no conversion or publication themselves.

FX event translation belongs to chart conversion. Audio rendering belongs to the
music component. Source effect information remains available for both boundaries;
the current chart converter diagnoses untranslated audible behavior.

## Errors and output

Expected errors derive from `Ksm2SdvxError`. Chart and resource errors belong to
their components; general output errors are shared. Unexpected programming errors
are not caught as ordinary input failures. Diagnostics carry stable codes,
severity, stage, feature, source location, and optional integer pulse. Shared
diagnostics do not depend on chart-specific types.

Chart output stages VOX and report files before replacing either. Each replacement
is atomic; the pair is not a filesystem transaction. Failure of the second
replacement is reported and can leave a new chart beside the previous report.

## Verification

Synthetic golden fixtures and typed-model tests cover chart behavior. Inspection
tests check resource handling and filesystem contents before and after execution.
CLI integration tests cover command options, exit codes, and file output. Local
verification includes lint, formatting, strict type checking, tests, and package
builds.
