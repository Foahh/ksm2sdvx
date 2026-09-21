# KSON support gaps

This is the implementation backlog for KSON version 1 conversion with the `vox13`
profile. It describes converter limitations, not proof that the target game
cannot represent a feature. Update the relevant entries when support changes.
See [conversion compatibility](compatibility.md) for supported behavior and
approximation details.

## Unsupported chart fields

These fields are parsed and retained, but their behavior is not emitted into
VOX. Default conversion reports omissions; `--strict` rejects unsupported
features. Empty or inactive values may not produce a diagnostic.

| KSON field | Remaining work | Diagnostic |
| --- | --- | --- |
| `beat.stop` | Convert nonzero stop intervals; define interaction with scroll-speed events | `UNSUPPORTED_STOP` |
| `camera.cam.body.zoom_side` | Map this camera graph | `UNSUPPORTED_CAMERA` |
| `camera.cam.body.rotation_deg` | Map this camera graph | `UNSUPPORTED_CAMERA` |
| `camera.cam.body.center_split` | Map this camera graph | `UNSUPPORTED_CAMERA` |
| `camera.cam.pattern.laser.slam_event.swing` | Convert swing events and their `scale`, `repeat`, and `decay_order` parameters | `UNSUPPORTED_CAMERA` |
| `camera.tilt`: `biggest`, `keep_normal`, `keep_biggest`, `zero` | Map the remaining automatic tilt modes | `UNSUPPORTED_TILT_MODE` |
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

The chart's default effect tables and note sample selectors do not implement
authored audio. Track standalone VOX translation separately from package audio
rendering: rendering an effect into music does not provide an interactive game
effect. When adding rendering support, update the package status as well as the
remaining standalone conversion gaps.

## Unsupported package fields and resources

| KSON field | Current limitation | Diagnostic |
| --- | --- | --- |
| `meta.title_translit`, `meta.artist_translit` | Retained without an automatic package metadata mapping | `UNSUPPORTED_PACKAGE_METADATA` |
| `meta.information`, `meta.std_bpm` | Retained without a package output mapping | `UNSUPPORTED_PACKAGE_METADATA` |
| `meta.title_img_filename`, `meta.artist_img_filename`, `meta.icon_filename` | Referenced resources are not included in the package | `UNSUPPORTED_PACKAGE_RESOURCE` |
| `audio.bgm.legacy.fp_filenames` | Alternate BGM resources are retained but not routed or packaged | `UNSUPPORTED_PACKAGE_RESOURCE` |
| Effect audio, keysound, and background resource references | Inventoried but not processed into package output | `UNSUPPORTED_PACKAGE_RESOURCE` |

Package omissions warn by default and fail strict package creation. A successful
standalone chart conversion does not establish package support for these fields.
Resource existence checks do not establish that a resource will be used.

## Partial support and validation limits

| Feature | Remaining limitation |
| --- | --- |
| Manual `camera.tilt` | Isolated nonzero values without a span are omitted with `ISOLATED_TILT_VALUE` |
| Spin and half-spin | Events without a suitable slam are omitted with `UNMATCHED_SPIN`; fallback direction and ambiguous association are approximations |
| Spin duration | Uses the documented duration mapping; durations not divisible by 60 KSON pulses fail conversion |
| Curved lasers and manual tilt | Sampled at `--curve-step`; no continuous error bound |
| Zoom top/bottom | Joint projection with sampled landmark tolerance; unreachable projections or tolerance failures on the target grid reject conversion |
| `beat.scroll_speed` ramps | Sampled as held multipliers; no continuous interpolation or note-travel error bound |
| Negative `beat.scroll_speed` | Signed values are emitted and allowed in strict mode; reverse-scroll rendering and judgment remain unverified in gameplay |
| Timing | One VOX tick is five KSON pulses; unrepresentable source positions fail instead of rounding |

`beat.scroll_speed` already supports constant values, jumps, curves, zero, and
negative multipliers. Its zero values do not implement the separate `beat.stop`
field. Supported approximations are allowed in strict mode; invalid timing and
unrepresentable values fail in either mode.

## Retained data with no chart mapping required

Core metadata, BGM settings, and jacket references are handled by package
processing rather than VOX chart text. `editor` and `compat` remain source
annotations (`RETAINED_SOURCE_DATA`); they are not gameplay implementation gaps.

## Implementation entry points

- Source parsing and validation: `src/ksm2sdvx/chart/kson/`.
- Camera mapping and conditional omissions: `src/ksm2sdvx/chart/conversion/camera.py`.
- Scroll-speed conversion: `src/ksm2sdvx/chart/conversion/scroll.py`.
- Unsupported-feature accounting: `src/ksm2sdvx/chart/conversion/effects.py`.
- Package metadata and resource omissions: `src/ksm2sdvx/pipeline/build.py`.
- Target model, validation, and serialization: `src/ksm2sdvx/chart/vox/`.

For each implemented field, verify its timing and boundary behavior, emitted
output, diagnostics, and strict-mode handling. Keep any remaining approximation
or gameplay verification limit explicit in this backlog and the compatibility
documentation.
