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
| Zoom top/bottom | Joint projection of relative lane width and height, with sampled physical spans |
| Manual tilt | Fixed angular conversion, continuous winding and equivalent instantaneous orientations |
| Normal, bigger, keep_bigger tilt | Converted to existing VOX mode codes |
| Other auto tilt modes, including zero | Explicit unsupported-feature diagnostics |
| Spins and half-spins | Positive durations attach to matching slams; zero-duration events emit no roll and are reported as no-ops |
| Swing and other camera body controls | Preserved with unsupported-feature diagnostics |
| Scroll speed, including negative values | Converted to signed ManualSpeed updates; linear and curved ramps are sampled |
| Stops (`beat.stop`) | Preserved with unsupported-feature diagnostics |
| Effect definitions, automation, invocations | Preserved; standalone chart output diagnoses absent audio rendering |
| Keysounds | Preserved; package creation renders supported chip samples |
| Metadata, BGM and artwork references | Preserved for package processing; their absence from VOX text does not fail strict chart conversion |
| Background behavior, gauge, client extensions | Retained; unsupported behavior diagnosed |
| Editor and compatibility annotations | Retained as deferred source data |

One target tick is five source pulses. Conversion rejects unrepresentable timing
instead of rounding it. Sampling intervals must be positive multiples of five.
Laser and tilt curve sampling is deterministic but is not an error-bounded
approximation. Zoom sampling also checks intermediate projected landmarks.
Source anchors and jumps are preserved; analytical curve controls are not written to VOX.

The converter writes five laser effect definitions, twelve no-effect FX pairs,
and twenty-four disabled parameter assignments. FX holds reference pair `2`
(the first pair); FX chips use sample `0`. These tables complete the VOX structure;
standalone chart conversion diagnoses authored audio it cannot produce.
Package creation bakes supported effects into each difficulty's music, disables
native FX and laser processing, and uses sample `255` for rendered gold FX chips.
Ordinary silent chips retain sample `0`.

The target model supports explicit beat resolution, BPM pause flags and options,
effect definitions and modulation, optional chain counts, post-effects, scripts,
and locked controllers. That target-format support does not imply a KSON mapping
for stops, FX or scripted visuals.

`beat.scroll_speed` uses instantaneous `ManualSpeed` multipliers, independent of
BPM. Constant values and jumps are retained, including negative multipliers,
zero-speed pauses and values above 1. Linear and curved ramps become held speed
updates every `--curve-step` KSON pulses (15 by default), with every source anchor retained in
the timing grid. This is a stepwise approximation, not continuous interpolation
or an error-bounded match of note travel. Smaller intervals reduce the step size;
intervals and source anchors must fit the five-pulse target grid. Redundant
unchanged updates are omitted. Before the first anchor its incoming value applies;
at an anchor its outgoing value applies, and the final value persists.
Scroll events contribute to the chart end without changing BPM or note timing.
Negative multipliers are emitted unchanged and accepted in strict conversion;
reverse-scroll rendering and judgment behavior have not been verified in gameplay.
The separate `beat.stop` field remains unsupported, even though zero values in
`scroll_speed` are converted. See [vox2ksh](https://github.com/whiteou7/vox2ksh)
for the upstream VOX reference.

Spin conversion sets VOX's total duration to twice the KSON duration and reports
`SPIN_DURATION_MAPPING` as an approximation. It never selects a triple roll for a
long single spin. Fractional-beat encodings use tenths of a quarter note; source
durations must be multiples of 60 pulses for this mapping, otherwise conversion
fails without rounding. End position includes the full emitted VOX duration.

Zoom conversion jointly matches relative lane width at the judgment row and lane
height, then inverts the target normalization. Negative bottom values use a
different source slope from positive values. Values outside 0–100 use the same
projection equations, subject to visibility and normalization limits. Source
geometry crossing the camera plane, reversed lanes, an unavailable judgment-row
intersection, and unreachable target projections fail with the pulse and values.
Values are not clamped or extended using a fitted line.

Moving zoom spans are at most `--curve-step` pulses long and are refined until
quarter-, half- and three-quarter-span landmark errors are at most 0.25 pixels
in the reference projection. This is a sampled numerical tolerance, not a
continuous or playback error guarantee. Failure to meet it on the five-pulse
grid rejects conversion. Both controls share sampling times; changing one can
also adjust the other. Initial and isolated zoom values are retained.

Manual tilt uses `-8/19` target units per source unit. One raw source unit is
10 degrees; editor 3600% is raw 36, one turn. Continuous ramps retain their signed
turn count. Instantaneous changes select an equivalent orientation within half
a turn, so a jump from 0 to 36 does not introduce a target revolution. Target
smoothing, different rotation pivots and judgment overlays remain approximation
limits, including combined zoom/tilt and continuous full turns. A numeric manual
value, including zero, holds until the next automatic setting or the chart ends.

Realize anchors are `(17.12, 60.12, 110.12)` for radius and `(0.28, 0.72, 1.57)`
for pitch. Camera mapping is fixed; there are no camera gain or scale options.
It matches selected lane landmarks rather than the entire rendered scene.
Source projection attribution: [K-Shoot MANIA](https://github.com/kshootmania/ksm-v2);
its license notice is included in the distribution.

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
`meta.disp_bpm` may be omitted or empty; supplied text is retained as display
metadata. VOX timing and package BPM ranges use the actual `beat.bpm` events.

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
| Chart audio | ksmaudio DSP effects, laser filters, switch-audio routing, file and built-in chip keysounds | Windows x64 renderer; custom slam sounds and legacy alternate-BGM routing are diagnosed |
| Gameplay and preview | Each difficulty has separately rendered and normalized audio; preview comes from the original track | Baked effects are independent of player input; arcade slam feedback remains enabled |
| Audio timing | Positive KSON offset trims, negative pads silence; previews use original audio coordinates | All charts in a package must share the music file, offset, volume and preview timing |
| Jackets | 8-bit RGB PNG, 108/128/300/676 pixels square; always contain with black margins | Symbolic presets need an explicit file override; transparent pixels composite onto black |
| Artwork credits | KSON `meta.jacket_author`; shared and per-chart `jacket.author` overrides | No separate chart-level credit setting |
| Metadata | New entry from selected charts and explicit target defaults, encoded as CP932 XML | Text outside that encoding is rejected; no existing song entry is used as a template |
| IDs | Explicit unused ordinary song ID, 1–3071 for the supported target | Checks the reference database, not other installed mods |
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

Package creation renders supported FX and chip keysounds. Custom slam sounds,
legacy alternate-BGM routing, unknown audio features, unmapped optional metadata
and other unsupported resources remain diagnosed. `--strict` rejects those omissions, while supported
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
