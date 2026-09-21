# Package creation

`ksm2sdvx package` produces a new-song mod directory for
[ifs_layeredfs](https://github.com/mon/ifs_layeredfs). It converts charts, music,
previews, jackets and a music database entry. It does not install the result into
a running game.

Package creation requires Windows with the Windows Media Format runtime, plus
FFmpeg and FFprobe on `PATH`. Use `--ffmpeg` and `--ffprobe` to select executables.
Python runtime dependencies remain standard-library only.

```text
uv run ksm2sdvx package package.toml --game-data reference/data
```

## Command options

| Argument or option | Default | Meaning |
| --- | --- | --- |
| `MANIFEST` | Required | Path to the TOML configuration |
| `--game-data PATH` | Required | Reference data directory containing `others/music_db.xml` and `graphics/s_jacket00.ifs` |
| `-o PATH`, `--output PATH` | `output/data_mods/<name>` | New mod directory; must not exist or be inside the reference data directory |
| `--ffmpeg EXECUTABLE` | `ffmpeg` | Audio and image processing executable |
| `--ffprobe EXECUTABLE` | `ffprobe` | Image probing executable |
| `--strict` | Off | Reject omitted source features, including unmapped package metadata/resources |
| `--curve-step PULSES` | `15` | Laser/tilt curve and scroll-speed ramp sampling interval, and maximum moving zoom span; positive integer divisible by 5 |
| `-h`, `--help` | — | Show command help |

Command-line paths resolve from the working directory. `-o` names the mod
directory itself, for example `exports/data_mods/my_song`. The reference database
and archive are read-only inputs. These command options are not TOML fields.
Camera mapping and its projection limits are described in
[conversion compatibility](compatibility.md#chart-conversion).

## Complete configuration reference

[examples/package.toml](../examples/package.toml) contains every supported field,
with optional source overrides commented out. Place it in your song directory
and set the song ID, names and chart paths. The tables below describe all accepted
fields. Unknown keys, invalid types and empty strings are rejected. Omit an
optional field to use its default; TOML has no null value.

The configuration is unversioned TOML. `metadata.version` is the target music
database's version field. JSON output reports have their own schema versions.

### Top-level fields

| Field | Required/default | Meaning and constraints |
| --- | --- | --- |
| `name` | Required | Shared name for the mod directory and resource filenames; starts with an ASCII letter or digit, followed by ASCII letters, digits, `_` or `-` |
| `song_id` | Required | Unused integer ID, 1–3071 for the supported target |
| `charts` | At least one `[[charts]]` table | Explicit charts belonging to this song |
| `metadata` | Optional table | Shared song metadata overrides |
| `music` | Optional table | Loudness and peak settings |
| `jacket` | Optional table | Shared artwork and credit overrides |

IDs already in the reference database are rejected. Assign IDs that also avoid
other installed mods. The supported target uses fixed song tables: IDs above
3071 are rejected. LayeredFS does not expand those tables. The example ID 3000
is not reserved; verify that it is unused in your installation.

One command creates one new song; existing songs are not
replaced and song grouping is never inferred. Metadata entries are constructed
from source values and target defaults without selecting an existing song.

For `name = "my_song"` and `song_id = 3000`, the default mod directory is
`output/data_mods/my_song`, and its resources use the stem `3000_my_song`.
The same name supplies the database's `ascii` field. The displayed song title
comes from KSON or `metadata.title`.

The TOML file's directory is the source root. Chart paths and jacket overrides
resolve from that directory, regardless of where the command is run. KSON
resource references resolve from their owning chart's directory. All source
files must remain inside the TOML directory, including after resolving symlinks.

### `[metadata]`

All fields are optional; omitting the table uses the defaults below.

| Field | Default | Meaning and constraints |
| --- | --- | --- |
| `title` | KSON `meta.title` | Shared title override; without it, all selected charts must agree |
| `artist` | KSON `meta.artist` | Shared artist override; without it, all selected charts must agree |
| `title_yomigana` | Resolved title | Title reading; nonempty string |
| `artist_yomigana` | Resolved artist | Artist reading; nonempty string |
| `volume` | `91` | Database playback volume, integer 0–65535; separate from audio normalization |
| `version` | `7` | Target database version field, integer 1–255 |
| `distribution_date` | Local build date | Calendar date as an integer `YYYYMMDD`, for example `20260101` |
| `license_text` | Omitted | License or copyright text; nonempty string |
| `bg_no` | `2` | Background control, integer 0–65535 |
| `genre` | `0` | Genre control, integer 0–4294967295 |
| `is_fixed` | `1` | Database control, integer 0–255 |
| `demo_pri` | `0` | Demo priority, integer −128–127 |
| `inf_ver` | `2` with an infinite chart, otherwise `0` | Infinite-version control, integer 0–255 |

Database text must be representable in Windows Shift-JIS (CP932). BPM minimum and
maximum are derived from all selected charts' BPM events, in exact hundredths.

### `[music]`

Both fields are optional; omitting the table uses −11 LUFS and −1.0 dBTP.

| Field | Default | Meaning and constraints |
| --- | --- | --- |
| `target_lufs` | `-11` | Integrated loudness target, finite number from −70 to 0 LUFS |
| `true_peak_dbtp` | `-1` | Peak ceiling before encoding, finite number from −20 to 0 dBTP |

Music paths, offsets, source volume and preview timing come from KSON, rather
than TOML overrides:

| KSON field | Default | Package behavior |
| --- | --- | --- |
| `audio.bgm.filename` | Required for package creation | Shared music file |
| `audio.bgm.offset` | `0` ms | Positive trims the start; negative pads silence |
| `audio.bgm.vol` | `1` | Positive amplitude multiplier applied to the loudness target |
| `audio.bgm.preview.offset` | `0` ms | Nonnegative start time in the original audio |
| `audio.bgm.preview.duration` | `15000` ms | Positive preview duration |

All selected charts must share the resolved music file and these audio settings.

### `[jacket]` and `[charts.jacket]`

Both tables accept the same fields. A per-chart value overrides only that field;
other fields continue to inherit independently.

| Field | Fallback after shared settings | Meaning and constraints |
| --- | --- | --- |
| `source` | KSON `meta.jacket_filename` | Image path relative to the TOML directory; an explicit file is needed for a symbolic preset |
| `author` | KSON `meta.jacket_author`, or empty if absent | Artwork credit; overrides must be nonempty strings |

The precedence is `[charts.jacket]` → `[jacket]` → the fallback above. Place each
`[charts.jacket]` table after the `[[charts]]` entry it belongs to. Artwork credit
is set through `author` here or read from KSON.

### `[[charts]]`

| Field | Required/default | Meaning and constraints |
| --- | --- | --- |
| `path` | Required | KSON file relative to the TOML directory |
| `slot` | Required | `"novice"`, `"advanced"`, `"exhaust"`, `"infinite"`, `"maximum"` or `"ultimate"` |
| `level_tenths` | KSON `meta.level` × 10 | Target difficulty, integer 1–255; 165 represents 16.5 |
| `max_exscore` | `0` with a warning | Maximum EX score, integer 0–2147483647; not calculated from notes |
| `price` | `-1` | Target database control, signed 32-bit integer (−2147483648–2147483647) |
| `limited` | `3` | Target database control, unsigned 8-bit integer (0–255) |
| `jacket_print` | `-2` | Jacket print control, signed 32-bit integer |
| `jacket_mask` | `0` | Jacket mask control, signed 32-bit integer |
| `radar` | Optional `[charts.radar]` table | Per-chart radar values described below |
| `jacket` | Optional `[charts.jacket]` table | Per-chart overrides described above |

Each source chart and target slot may appear only once. Repeat `[[charts]]` for
more difficulties; every unselected slot receives level zero. Chart author comes
from KSON `meta.chart_author`.

Only `path` and `slot` are required. Omit `price`, `limited` or any other optional
field to keep its default.

### `[charts.radar]`

This table belongs to the preceding `[[charts]]` entry. All six fields are optional
integers from 0 to 65535; missing values become zero with a warning. Radar values
are not calculated from notes. Supplying all six values suppresses that warning,
including when the supplied values are zero.

| Configuration field | XML field |
| --- | --- |
| `notes` | `notes` |
| `peak` | `peak` |
| `tsumami` | `tsumami` |
| `tricky` | `tricky` |
| `hand_trip` | `hand-trip` |
| `one_hand` | `one-hand` |

## Music and artwork

Music and previews use ASF containers with WMA Professional audio and a 32-byte
`S3V0` footer required for game playback, stereo at 44.1 kHz and approximately
384 kb/s. Positive KSON offsets trim the beginning;
negative offsets add silence. Preview intervals refer to the original audio
file. Package creation chooses one gain from the full track's integrated loudness
and the peak headroom of both the full track and preview.

The default loudness target is **−11 LUFS**, configurable through
`music.target_lufs`. FFmpeg measures integrated loudness and true peak; a constant
`volume` filter applies the smaller of the required loudness gain and available
peak headroom. It does not compress the signal's dynamics. KSON source volume
scales the loudness target. Silent audio and nonpositive source volume are
rejected because normalization cannot determine a finite gain.

`music.true_peak_dbtp` defaults to **−1 dBTP** and limits the signal before
encoding. Lossy encoding can raise the decoded peak; the processor measures the
result and reports that condition. The package report includes actual decoded
loudness and peak values. Database `volume` remains a separate playback control.

Jackets are 8-bit RGB PNGs: 300×300 standard, 108×108 small, 676×676 large and
128×128 selector. Images always use contain: the full image keeps its aspect
ratio with black margins. Transparent pixels composite onto black. A non-square
conversion is reported. All four sizes are produced for each selected chart.

```toml
[[charts]]
path = "hard.kson"
slot = "exhaust"

[charts.jacket]
source = "hard-jacket.png"
author = "Artwork author"
```

Use the standalone [audio and jacket commands](media.md) to process media without
building a package.

## Output and reports

For song 3000 in the exhaust slot, the output contains:

```text
my_song/
  others/music_db.merged.xml
  music/3000_my_song/
    3000_my_song_3e.vox
    3000_my_song.s3v
    3000_my_song_pre.s3v
    jk_3000_3.png
    jk_3000_3_s.png
    jk_3000_3_b.png
  graphics/s_jacket00_ifs/jk_3000_3_t.png
  ksm2sdvx-report.json
```

Place the finished `my_song` directory under the target's `data_mods` directory.
Selector images extend the existing `s_jacket00.ifs`; no copied game archive is
included. The XML fragment adds a new entry rather than duplicating an existing ID.

The schema-version-1 package report records chart conversion reports, source
paths relative to the package root, audio measurements, diagnostics and written
files. Uncomputed score/radar fields are reported.

## Conversion limits and failures

FX translation, keysounds, unmapped optional metadata and other unsupported
resources remain explicit omissions. `--strict` rejects these omissions;
supported chart approximations remain allowed. Warnings for uncomputed radar
and unspecified maximum EX score remain allowed in strict mode.

Per-difficulty audio selection, automatic song grouping, replacing existing songs
and automatic score/radar calculation are not implemented. Missing referenced
files, references outside the source root, invalid source/configuration data,
unrepresentable chart timing and ID/output collisions fail in either mode.

Success returns 0, expected input or processing failures return 1, and argument
errors return 2. Media or serialization failures do not publish a partial mod.
