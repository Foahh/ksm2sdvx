# KSON support gaps

This page lists KSON version 1 features that `ksm2sdvx` does not fully convert
with the `vox13` profile. It describes the converter's current behavior. See
[conversion compatibility](compatibility.md) for supported features and
approximation details.

Use [unsupported chart fields](#unsupported-chart-fields) for direct VOX mapping,
[audio status](#audio-status-offline-rendering-workaround) for effects rendered
into music, and [unsupported package fields](#unsupported-package-fields-and-resources)
for metadata and resource omissions.

## Unsupported chart fields

These fields are parsed and retained, but their behavior is not emitted into
VOX. Default conversion reports omissions; `--strict` rejects unsupported
features. Empty or inactive values may not produce a diagnostic. The audio rows
describe missing native VOX mappings. Package creation handles some of them by
rendering the sound into the music, as described below.

| KSON field | Remaining work | Diagnostic |
| --- | --- | --- |
| `camera.cam.body.zoom_side` | Map this camera graph | `UNSUPPORTED_CAMERA` |
| `camera.cam.pattern.laser.slam_event.swing` | Convert swing events and their `scale`, `repeat`, and `decay_order` parameters | `UNSUPPORTED_CAMERA` |
| `camera.tilt`: `biggest`, `keep_normal`, `keep_biggest` | Map the remaining automatic tilt modes | `UNSUPPORTED_TILT_MODE` |
| `audio.audio_effect.fx.def`, `audio.audio_effect.laser.def` | Implement authored effect definitions and parameters | `UNSUPPORTED_EFFECT_DEFINITION` |
| `audio.audio_effect.fx.param_change`, `audio.audio_effect.laser.param_change` | Implement timed effect parameter changes | `UNSUPPORTED_EFFECT_EVENT` |
| `audio.audio_effect.fx.long_event` | Implement FX hold effect invocations and overrides | `UNSUPPORTED_EFFECT_EVENT` |
| `audio.audio_effect.laser.pulse_event` | Implement laser effect selection events | `UNSUPPORTED_EFFECT_EVENT` |
| `audio.audio_effect.laser.peaking_filter_delay`, `audio.audio_effect.laser.legacy.filter_gain` | Implement filter delay and legacy gain behavior | `UNSUPPORTED_EFFECT_PARAMETER` |
| `audio.key_sound.fx.chip_event` | Implement chip samples and per-event volume | `UNSUPPORTED_KEYSOUND` |
| `audio.key_sound.laser.slam_event`, `.vol`, `.legacy.vol_auto` | Implement authored slam sounds and volume behavior | `UNSUPPORTED_KEYSOUND` |
| `bg` | Map authored background behavior and resources | `UNSUPPORTED_SOURCE_FEATURE` |
| `gauge.total` | Map custom gauge behavior | `UNSUPPORTED_SOURCE_FEATURE` |
| `impl` | Interpret applicable client-specific behavior | `UNSUPPORTED_SOURCE_FEATURE` |
| Unknown optional members | Add explicit mappings where applicable | `UNKNOWN_EXTENSION` |

## Audio status: offline-rendering workaround

Authored audio is supported through a workaround: render effects and chip
keysounds into difficulty-specific music before packaging. This does not
implement native, interactive VOX effects. The rendered effects play regardless
of player input, including missed notes and laser tracking.

| Feature | Workaround status |
| --- | --- |
| Supported FX and laser effect definitions, parameters, automation, and hold overrides | Baked into gameplay audio by the bundled renderer |
| Laser graphs, filter delay, and legacy filter gain | Used by the audio renderer independently of VOX curve sampling |
| `switch_audio` | Resolves referenced tracks for rendering |
| FX chip keysounds and per-event volume | Mixed into gameplay audio, including bundled presets and file-based samples |
| Native FX and laser filters | Disabled in package charts after successful rendering to avoid applying effects twice |
| Preview | Generated from the original music without baked chart effects |
| Custom slam sounds, slam volume behavior, legacy alternate BGM, and unknown audio extensions | Still unsupported; omissions are diagnosed and rejected in strict mode |

`audio --chart` renders audio only; `package` combines it with the matching VOX
chart. Standalone `chart` conversion and read-only `inspect` do not render audio
or resolve these native chart-mapping gaps. Package strictness accepts covered
audio features only after successful rendering. Missing required resources and
invalid effect parameters always fail. Arcade laser-slam feedback is retained.

The workaround is not a claim of exact KSM Editor output equivalence. Audio
level consistency and renderer fidelity remain verification limits.

## Unsupported package fields and resources

| KSON field | Current limitation | Diagnostic |
| --- | --- | --- |
| `meta.title_translit`, `meta.artist_translit` | Retained without an automatic package metadata mapping | `UNSUPPORTED_PACKAGE_METADATA` |
| `meta.information`, `meta.std_bpm` | Retained without a package output mapping | `UNSUPPORTED_PACKAGE_METADATA` |
| `meta.title_img_filename`, `meta.artist_img_filename`, `meta.icon_filename` | Referenced resources are not included in the package | `UNSUPPORTED_PACKAGE_RESOURCE` |
| `audio.bgm.legacy.fp_filenames` | Alternate BGM resources are retained but not routed or packaged | `UNSUPPORTED_PACKAGE_RESOURCE` |
| Unsupported audio and background resource references | Inventoried but not processed; supported switch-audio and chip-sample files are consumed by the audio workaround | `UNSUPPORTED_PACKAGE_RESOURCE` |

Package omissions warn by default and fail strict package creation. A successful
standalone chart conversion does not establish package support for these fields.
Resource existence checks do not establish that a resource will be used.

## Partial support and validation limits

| Feature | Remaining limitation |
| --- | --- |
| Spin and half-spin | Events without a suitable slam are omitted with `UNMATCHED_SPIN`; fallback direction and ambiguous association are approximations |
| Spin duration | Uses the documented duration mapping; durations not divisible by 60 KSON pulses fail conversion |
| Curved lasers and manual tilt | Sampled at `--curve-step`; no continuous error bound |
| Zero automatic tilt | Uses a manual hold; entry/exit transitions can differ from the source fade |
| Center split | Initial Morphing2 scale; playback and combinations with other camera controls remain unverified |
| Body rotation in degrees | Initial BIL_RotZ mapping; pivot and projection differ; playback and combined controls remain unverified |
| Zoom top/bottom | Joint projection with sampled landmark tolerance; unreachable projections or tolerance failures on the target grid reject conversion |
| `beat.scroll_speed` ramps | Sampled as held multipliers; no continuous interpolation or note-travel error bound |
| Negative `beat.scroll_speed` | Signed values are emitted and allowed in strict mode; reverse-scroll rendering and judgment remain unverified in gameplay |
| Stops combined with scroll-speed changes | Native pause markers and ManualSpeed updates are emitted independently; combined playback and ramp boundaries remain unverified |
| Timing | One VOX tick is five KSON pulses; unrepresentable source positions fail instead of rounding |

`beat.scroll_speed` already supports constant values, jumps, curves, zero, and
negative multipliers. The separate `beat.stop` field uses native pause markers
with merged stop intervals. Supported approximations are allowed in strict mode;
invalid timing and unrepresentable values fail in either mode.

## Retained data with no chart mapping required

Core metadata, BGM settings, and jacket references are handled by package
processing rather than VOX chart text. `editor` and `compat` remain source
annotations (`RETAINED_SOURCE_DATA`); they are not gameplay implementation gaps.

## Implementation entry points

- Source parsing and validation: `src/ksm2sdvx/chart/kson/`.
- Camera mapping and conditional omissions: `src/ksm2sdvx/chart/conversion/camera.py`.
- Scroll-speed conversion: `src/ksm2sdvx/chart/conversion/scroll.py`.
- BPM and stop conversion: `src/ksm2sdvx/chart/conversion/beat.py`.
- Unsupported-feature accounting: `src/ksm2sdvx/chart/conversion/effects.py`.
- Audio workaround: `src/ksm2sdvx/chart/audio.py`, `src/ksm2sdvx/music/renderer.py`, `native/`, and `src/ksm2sdvx/pipeline/audio.py`.
- Package metadata and resource omissions: `src/ksm2sdvx/pipeline/build.py`.
- Target model, validation, and serialization: `src/ksm2sdvx/chart/vox/`.

For each implemented field, verify its timing and boundary behavior, emitted
output, diagnostics, and strict-mode handling. Keep any remaining approximation
or gameplay verification limit explicit in this backlog and the compatibility
documentation.
