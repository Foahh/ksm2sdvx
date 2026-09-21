# Conversion compatibility

The `vox13` profile converts KSON format version 1 to VOX v13. Chart conversion
is used by `chart`, `inspect` and `package`. Audio, jacket and package processing
have additional behavior described below.

## Chart conversion

| Feature | Behavior |
| --- | --- |
| BT/FX chips and holds | Converted; lane mapping preserved |
| Meter and BPM changes | Exact rational positions; an initial BPM and meter are required |
| Straight lasers and slams | Converted with stable same-pulse ordering |
| Wide lasers | Width retained in normal and original laser tracks |
| Curved lasers | Sampled every 15 KSON pulses; original tracks retain control nodes |
| Zoom top/bottom and manual tilt | Configurable scales and linear spans |
| Normal, bigger, keep_bigger tilt | Converted to existing VOX mode codes |
| Other auto tilt modes, including zero | Explicit unsupported-feature diagnostics |
| Spins and half-spins | Attached to matching slams; duration mapping, fallback and ambiguity are reported |
| Swing and other camera body controls | Preserved with unsupported-feature diagnostics |
| Stops and nondefault scroll speed | Preserved with unsupported-feature diagnostics |
| Effect definitions, automation, invocations | Preserved; translation deferred and omissions diagnosed |
| Keysounds | Configuration/resources retained; audible behavior is not converted |
| Metadata, BGM and artwork references | Preserved for package processing; their absence from VOX text does not fail strict chart conversion |
| Background behavior, gauge, client extensions | Retained; unsupported behavior diagnosed |
| Editor and compatibility annotations | Retained as deferred source data |

One target tick is five source pulses. Conversion rejects unrepresentable timing
instead of rounding it. Sampling intervals must be positive multiples of five.
Sampling is deterministic but is not an error-bounded approximation. Source
anchors and jumps are preserved; analytical curve controls are not written to VOX.

The converter writes five laser effect definitions, twelve no-effect FX pairs,
and twenty-four disabled parameter assignments. FX holds reference pair `2`
(the first pair); FX chips use sample `0`. These tables complete the VOX structure;
translation of authored KSON effects remains unsupported and diagnosed.

The target model supports explicit beat resolution, BPM pause flags and options,
effect definitions and modulation, optional chain counts, post-effects, scripts,
and locked controllers. That target-format support does not imply a KSON mapping
for stops, scroll-speed behavior, FX or scripted visuals.

Spin conversion sets VOX's total duration to twice the KSON duration and reports
`SPIN_DURATION_MAPPING` as an approximation. It never selects a triple roll for a
long single spin. Fractional-beat encodings use tenths of a quarter note; source
durations must be multiples of 60 pulses for this mapping, otherwise conversion
fails without rounding. End position includes the full emitted VOX duration.

Camera defaults are top `0.0013225`, bottom `-0.00382` and tilt
`-0.4217946006575624`, with explicit Realize anchors `(17.12, 60.12, 110.12)` and
`(0.28, 0.72, 1.57)`. The converter multiplies values by the corresponding scale
and emits linear spans. Isolated nonzero camera/manual-tilt values without a span
are diagnosed as omitted.

Default conversion warns about omissions and emits the supported chart.
`--strict` fails for unsupported features; supported sampling and camera
approximations remain allowed. Invalid source data always fails. Unknown optional
members are retained and diagnosed rather than silently discarded.

Preset names are recognized in fields that allow them when they have no extension,
separator or drive prefix. File resources are resolved relative to each source
chart and must remain in the package root. Inspection verifies file existence;
the implemented media processors decode and validate files during conversion.
Package creation uses the TOML file's directory as that root; inspection takes
its root explicitly through `--root`.

## Typed APIs and source validation

Use the installed CLI or `load_kson`/`parse_kson` → `convert_chart` → `serialize_vox`
from `ksm2sdvx.chart`. The old root scripts and raw-dictionary API have no
compatibility wrappers. Callers must supply required KSON metadata and handle
typed results. Parsing rejects nulls, fractional pulses, boolean numeric values,
negative durations, nonfinite numbers, invalid ordering and prohibited overlaps.
A UTF-8 BOM is accepted with a diagnostic.

Generated headers name `ksm2sdvx`. End markers include supported timing and mode
events that occur after the last note. Separate manual tilt sequences
restart their node encoding instead of sharing one sequence across automatic
intervals.

The VOX model distinguishes `VoxBtNote`, `VoxFxChip`, and `VoxFxHold`.
Laser fields identify the effect selector and
the separate v13 C8 field. `Realize` keeps explicit C3–C7 values. Direct target
construction must supply the three complete effect tables and pass target
validation before serialization.

## Media and package conversion

| Component | Implemented behavior | Limits |
| --- | --- | --- |
| Audio | ASF/WMA Professional, stereo 44.1 kHz, approximately 384 kb/s; default −11 LUFS through constant gain | Windows encoder required; peak headroom can prevent reaching the requested loudness |
| Audio timing | Positive KSON offset trims, negative pads silence; previews use original audio coordinates | All charts in a package must share the music file, offset, volume and preview timing |
| Jackets | 8-bit RGB PNG, 108/128/300/676 pixels square; always contain with black margins | Symbolic presets need an explicit file override; transparent pixels composite onto black |
| Artwork credits | KSON `meta.jacket_author`; shared and per-chart `jacket.author` overrides | No separate chart-level credit setting |
| Metadata | New entry from selected charts and explicit target defaults, encoded as CP932 XML | Text outside that encoding is rejected; no existing song entry is used as a template |
| IDs | Explicit unused ID, 1–32767; 10001+ recommended | Checks the reference database, not other installed mods |
| Package output | New `data_mods/<name>` directory with charts, media, selector artwork and XML fragment | No song replacement or automatic grouping; destination must be new |
| Score and radar | Explicit maximum EX score and six per-chart radar values accepted; unspecified values become zero with warnings | Automatic calculation is not implemented |

Jacket override precedence is per-chart settings → shared settings → KSON for
source/author. `[charts.jacket]` belongs to the preceding
`[[charts]]` entry. See the [complete configuration](package.md#complete-configuration-reference)
for all fields, defaults and allowed values. There is no configuration schema
version or template selector.

The `audio` and `jacket` commands expose the same processors independently. See
[media commands](media.md) for all arguments. Peak limits apply before lossy
encoding; decoded output peaks are measured and overshoots are reported.

Package creation diagnoses FX, keysounds, unmapped optional metadata and other
unsupported resources. `--strict` rejects those source omissions, while supported
approximations and the score/radar warnings remain allowed. Invalid resources,
timing and configuration fail in either mode.

## Inspection and reports

`ksm2sdvx.pipeline.inspect_package` and `ksm2sdvx inspect` convert charts in memory
and inventory resources without writing files. Inspection preserves per-chart
metadata and audio offsets. It does not infer songs or verify media encoding.

Inspection JSON uses schema version 2. It contains `schema_version`, `valid`,
`root`, `charts`, `assets`, and `diagnostics`; resource uses identify their owning
`source` file. Resource diagnostics use the `inspect` stage. Chart and package
reports use schema version 1. Package reports include chart reports, relative
source paths, audio measurements, diagnostics and the output file inventory.
Report schema versions are independent of the unversioned TOML configuration.
