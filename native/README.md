# Offline renderer

`ksm2sdvx-render` is a private application helper built against the pinned
[ksmaudio](https://github.com/kshootmania/ksmaudio) dependency. It decodes audio
without opening a playback device and processes ksmaudio DSP instances in their
declared priority order.

```text
ksm2sdvx-render --request REQUEST.json --output OUTPUT.wav
```

The Python music component resolves resources and converts every input to stereo
44.1 kHz floating-point WAV before invoking the helper. Output is the same PCM
format, with authored effects, relative gains, and chip samples mixed in. Loudness
normalization and S3V encoding happen afterward in Python. KSM's playback master
compressor is not applied.

The internal request protocol has `protocol_version: 1`, `sample_rate: 44100`,
`duration_frames`, `offset_frames`, `bgm_volume`, `tracks`, `samples`, and `program`.
Resource arrays contain `id` and `path` records. The required main track uses ID
`main`; switch tracks use their authored filenames; chip samples use the compiler's
resource IDs. Positive offsets trim the source; negative offsets insert silence.

The chart program contains tempo events, ordered effect definitions, parameter
changes, FX holds and invocations, laser selection events and source graphs,
keysounds, `key_sound_polyphony`, and the peaking-filter delay. All event frames use
chart time. Tempo events and graph points also retain pulse positions so a curve
spanning a tempo change is evaluated in its original coordinate system.

Processing uses blocks of at most 64 frames, split at every event boundary. FX
overrides follow the most recently started hold, with right-lane precedence for a
tie. Parameter changes persist underneath note overrides. Inactive parameter
values remain effective while their bus is active. Each switched FX track keeps
its own built-in laser-filter state. Relative BGM gain is applied to the processed
music before mixing chip samples.
Each sample has one voice by default, or ten for the applicable source compatibility
setting. When the pool is full, retriggering replaces its longest-playing voice.

A successful call writes one JSON receipt to stdout containing PCM frame count,
channel count, sample rate, runtime versions, and effect/keysound counts. An
expected failure returns exit code 1 and a JSON `error` with `code` and `message`.
Argument errors return 2. Diagnostic logs use stderr. The caller owns temporary
output cleanup and atomic publication.

Build with `BUILD_TESTING=ON` and run CTest to exercise the native renderer with
generated audio. Tests cover every DSP family, frame boundaries, parameter
precedence, laser jumps, offsets, chip retriggering, switched tracks, deterministic
output, and invalid effect parameters.
