# Conversion compatibility

The `vox13` profile converts KSON format version 1 to VOX v13.
The table below lists the behavior implemented by this package.

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
| Metadata, BGM and artwork references | Deferred package data; do not fail strict chart conversion |
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
chart and must remain in the package root. Inspection verifies file existence; media
decoding and target-format suitability require processing implementations.

## Breaking migration

The root script invocation, raw-dictionary API and old JSON report are removed.
Use the installed CLI or `load_kson`/`parse_kson` → `convert_chart` → `serialize_vox`.
Existing callers must supply required metadata and handle the new typed results.
Generated headers now name `ksm2sdvx`. End markers now include supported timing
and mode events that occur after the last note. Separate manual tilt sequences
restart their node encoding instead of sharing one sequence across automatic
intervals.

The VOX model now distinguishes `VoxBtNote`, `VoxFxChip`, and `VoxFxHold` instead
of the former generic button row. Laser fields identify the effect selector and
the separate v13 C8 field. `Realize` keeps explicit C3–C7 values. Direct target
construction must supply the three complete effect tables. No aliases preserve
the earlier incomplete target API.

## Package and API names

Install `ksm2sdvx` and import chart operations from `ksm2sdvx.chart`. Package
inspection is available through `ksm2sdvx.pipeline.inspect_package` and the
`ksm2sdvx inspect` command. The earlier package, command, root exports, and package
operation names have been removed without aliases.

Inspection JSON uses schema version 2. It contains `schema_version`, `valid`,
`root`, `charts`, `assets`, and `diagnostics`; resource uses identify their owning
`source` file. The fixed deferred-operations list has been removed, and resource
diagnostics use the `inspect` stage. Chart reports retain schema version 1.

Chart output behavior is unchanged by this package migration apart from the
generated project-name header. Music, jacket, metadata conversion, and package
writing expose interfaces only and have no executable commands.
