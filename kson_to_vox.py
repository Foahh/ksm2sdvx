"""Convert KSON format_version 1 charts to playable/editable VOX v13."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from fractions import Fraction
import json
import math
from pathlib import Path

from kson_curve_fit import curve


DEFAULT_ZOOM_TOP_SCALE = 0.0013225
DEFAULT_ZOOM_BOTTOM_SCALE = -0.00382
DEFAULT_TILT_SCALE = -0.4217946006575624
CAMERA_REALIZE_ANCHORS = {
    'CAM_Radi': (3, (17.12, 60.12, 110.12)),
    'CAM_RotX': (4, (0.28, 0.72, 1.57)),
}


class ConversionError(ValueError):
    pass


def graph_value(v, outgoing=False):
    return float(v[-1 if outgoing else 0]) if isinstance(v, list) else float(v)


def graph_parts(point):
    """Return pulse, incoming value, outgoing value, and curve controls."""
    if not isinstance(point, list) or len(point) not in (2, 3):
        raise ConversionError(f'Invalid graph point: {point}')
    pulse = int(point[0])
    raw = point[1]
    incoming, outgoing = graph_value(raw), graph_value(raw, True)
    controls = point[2] if len(point) == 3 else [0.0, 0.0]
    if not isinstance(controls, list) or len(controls) != 2:
        raise ConversionError(f'Invalid graph curve controls: {controls}')
    a, b = map(float, controls)
    if (pulse < 0 or not all(math.isfinite(v) for v in (incoming, outgoing, a, b))
            or not all(0 <= v <= 1 for v in (a, b))):
        raise ConversionError(f'Invalid graph point: {point}')
    return pulse, incoming, outgoing, (a, b)


def sampled_graph_segments(points, step=15):
    """Expand a KSON numeric graph into VOX-compatible linear segments."""
    parsed = [graph_parts(point) for point in points]
    if any(parsed[i + 1][0] <= parsed[i][0] for i in range(len(parsed) - 1)):
        raise ConversionError('Graph pulses must be strictly increasing')
    segments, jumps = [], []
    for i, (pulse, incoming, outgoing, controls) in enumerate(parsed):
        if incoming != outgoing:
            jumps.append((pulse, incoming, outgoing))
        if i + 1 == len(parsed):
            continue
        next_pulse, next_incoming, _, _ = parsed[i + 1]
        a, b = controls
        anchors = [(pulse, outgoing)]
        if abs(a - b) > 1e-12:
            for y in range(pulse + step, next_pulse, step):
                x = (y - pulse) / (next_pulse - pulse)
                anchors.append((y, outgoing + (next_incoming - outgoing) * curve(x, a, b)))
        anchors.append((next_pulse, next_incoming))
        segments.extend((y0, y1, v0, v1)
                        for (y0, v0), (y1, v1) in zip(anchors, anchors[1:]))
    return segments, jumps


class Timeline:
    def __init__(self, changes):
        changes = changes or [[0, [4, 4]]]
        self.changes = []
        self.starts = []
        for row in changes:
            measure, signature = row
            measure, n, den = int(measure), int(signature[0]), int(signature[1])
            if measure < 0 or n <= 0 or den <= 0 or (self.changes and measure <= self.changes[-1][0]):
                raise ConversionError(f'Invalid time signature change: {row}')
            start = Fraction(0)
            if self.changes:
                pm, pn, pd = self.changes[-1]
                start = self.starts[-1] + (measure-pm)*Fraction(960*pn, pd)
            elif measure != 0:
                raise ConversionError('The first time signature must begin at measure 0')
            self.changes.append((measure, n, den))
            self.starts.append(start)
        self.measures = [v[0] for v in self.changes]

    def position(self, pulse):
        pulse = Fraction(pulse)
        if pulse < 0 or pulse.denominator != 1:
            raise ConversionError(f'Invalid KSON pulse: {pulse}')
        i = bisect_right(self.starts, pulse)-1
        if i < 0:
            raise ConversionError(f'Pulse precedes chart: {pulse}')
        cm, n, den = self.changes[i]
        measure_len = Fraction(960*n, den)
        measure = cm + int((pulse-self.starts[i]) // measure_len)
        within = pulse-(self.starts[i]+(measure-cm)*measure_len)
        beat_len = Fraction(960, den)
        beat = int(within // beat_len)+1
        tick_pulse = within-(beat-1)*beat_len
        tick = tick_pulse/Fraction(5)
        if tick.denominator != 1:
            raise ConversionError(f'Pulse {pulse} cannot be represented on the VOX 1/48-quarter grid')
        return f'{measure+1:03},{beat:02},{int(tick):02}'


def button_parts(note):
    if isinstance(note, int):
        return note, 0
    if not isinstance(note, list) or len(note) != 2:
        raise ConversionError(f'Invalid button note: {note}')
    return int(note[0]), int(note[1])


def expand_laser(section, step=15):
    if not isinstance(section, list) or len(section) not in (2, 3):
        raise ConversionError(f'Invalid laser section: {section}')
    start, points = int(section[0]), section[1]
    wide = int(section[2]) if len(section) == 3 else 1
    if wide not in (1, 2) or not points:
        raise ConversionError('Laser width must be 1 or 2 and points cannot be empty')
    emitted = []
    for i, point in enumerate(points):
        if len(point) not in (2, 3):
            raise ConversionError(f'Invalid laser point: {point}')
        ry, raw = int(point[0]), point[1]
        before, after = graph_value(raw), graph_value(raw, True)
        if not 0 <= before <= 1 or not 0 <= after <= 1:
            raise ConversionError(f'Laser position outside 0..1: {point}')
        absolute = start+ry
        if not emitted or emitted[-1] != (absolute, before):
            emitted.append((absolute, before))
        if after != before:
            emitted.append((absolute, after))
        if i+1 == len(points):
            continue
        next_point = points[i+1]
        next_ry = int(next_point[0])
        if next_ry <= ry:
            raise ConversionError('Laser relative pulses must be strictly increasing')
        target = graph_value(next_point[1])
        controls = point[2] if len(point) == 3 else [0.0, 0.0]
        a, b = float(controls[0]), float(controls[1])
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (a, b)):
            raise ConversionError(f'Invalid laser curve controls: {controls}')
        curved = abs(a-b) > 1e-12
        if curved:
            for rel in range(ry+step, next_ry, step):
                x = (rel-ry)/(next_ry-ry)
                value = after+(target-after)*curve(x, a, b)
                emitted.append((start+rel, value))
        if not emitted or emitted[-1] != (start+next_ry, target):
            emitted.append((start+next_ry, target))
    rows = []
    if len(emitted) == 1:
        emitted.append(emitted[0])
    for i, (pulse, value) in enumerate(emitted):
        marker = 1 if i == 0 else 2 if i == len(emitted)-1 else 0
        rows.append((pulse, value, marker, wide))
    return rows


def section(name, rows):
    return f'#{name}\n' + ('\n'.join(rows)+'\n' if rows else '') + '#END\n'


def convert_kson(chart, *, curve_step=15,
                 zoom_top_scale=DEFAULT_ZOOM_TOP_SCALE,
                 zoom_bottom_scale=DEFAULT_ZOOM_BOTTOM_SCALE,
                 tilt_scale=DEFAULT_TILT_SCALE):
    if int(chart.get('format_version', -1)) != 1:
        raise ConversionError('Only KSON format_version 1 is supported')
    if curve_step <= 0 or curve_step % 5:
        raise ConversionError('curve_step must be a positive multiple of 5 KSON pulses')
    for name, value in (('zoom_top_scale', zoom_top_scale),
                        ('zoom_bottom_scale', zoom_bottom_scale),
                        ('tilt_scale', tilt_scale)):
        if not math.isfinite(value):
            raise ConversionError(f'{name} must be a finite number')
    beat = chart.get('beat', {})
    timeline = Timeline(beat.get('time_sig', [[0, [4, 4]]]))
    notes = chart.get('note', {})
    bt = notes.get('bt', [[], [], [], []])
    fx = notes.get('fx', [[], []])
    lasers = notes.get('laser', [[], []])
    if len(bt) != 4 or len(fx) != 2 or len(lasers) != 2:
        raise ConversionError('note.bt/fx/laser must contain 4/2/2 lanes')
    tracks = {i: [] for i in range(1, 9)}
    original_lasers = {1: [], 8: []}
    laser_entries = {1: [], 8: []}
    slam_targets = []
    end = 0
    counts = {'bt': 0, 'fx': 0, 'laser_sections': 0, 'wide_laser_sections': 0,
              'laser_rows': 0, 'original_laser_rows': 0, 'spin_events': 0,
              'half_spin_events': 0, 'camera_rows': 0, 'manual_tilt_rows': 0,
              'auto_tilt_events': 0}
    for track, lane in zip((3, 4, 5, 6), bt):
        for note in lane:
            pulse, length = button_parts(note)
            if pulse % 5 or length % 5:
                raise ConversionError(f'Button note is outside VOX grid: {note}')
            tracks[track].append((pulse, f'{timeline.position(pulse)}\t{length//5}\t{2 if length else 0}'))
            end = max(end, pulse+length); counts['bt'] += 1
    for track, lane in zip((2, 7), fx):
        for note in lane:
            pulse, length = button_parts(note)
            if pulse % 5 or length % 5:
                raise ConversionError(f'FX note is outside VOX grid: {note}')
            tracks[track].append((pulse, f'{timeline.position(pulse)}\t{length//5}\t0'))
            end = max(end, pulse+length); counts['fx'] += 1
    for track, lane in zip((1, 8), lasers):
        serial = 0
        for laser in lane:
            rows = expand_laser(laser, curve_step)
            section_entries = []
            for pulse, value, marker, wide in rows:
                if pulse % 5:
                    raise ConversionError(f'Laser sample is outside VOX grid: {pulse}')
                fields = [timeline.position(pulse), f'{value:.6f}', marker, 0, 0, wide, 0, 0]
                # v13 has an unknown C8 after curve type and roll/swing length at C9.
                fields.extend([0, 0])
                entry = [pulse, serial, fields]
                laser_entries[track].append(entry)
                section_entries.append(entry)
                serial += 1
            for before, after in zip(section_entries, section_entries[1:]):
                if before[0] == after[0]:
                    delta = float(after[2][1]) - float(before[2][1])
                    if delta:
                        slam_targets.append({'pulse': before[0],
                                             'direction': 1 if delta > 0 else -1,
                                             'entry': before, 'assigned': False})
            end = max(end, rows[-1][0]); counts['laser_sections'] += 1
            counts['wide_laser_sections'] += rows[0][3] == 2
            counts['laser_rows'] += len(rows); counts['original_laser_rows'] += len(rows)

    camera = chart.get('camera', {})
    if not isinstance(camera, dict):
        raise ConversionError('camera must be an object')
    camera_unmapped = []
    camera_warnings = []
    slam_events = (camera.get('cam', {}).get('pattern', {}).get('laser', {})
                   .get('slam_event', {}))

    def roll_encoding(kind, length):
        if kind == 'spin':
            if length >= 960 and length % 240 == 0:
                return 4, length // 240
            return (1, length // 120) if length % 120 == 0 else (6, length // 15)
        return (5, length // 120) if length % 120 == 0 else (7, length // 15)

    for kind in ('spin', 'half_spin'):
        for event in slam_events.get(kind, []):
            if not isinstance(event, list) or len(event) != 3:
                raise ConversionError(f'Invalid {kind} event: {event}')
            pulse, direction, length = map(int, event)
            if pulse % 5 or direction not in (-1, 1) or length <= 0 or length % 15:
                raise ConversionError(f'Unrepresentable {kind} event: {event}')
            matches = [target for target in slam_targets
                       if not target['assigned'] and target['pulse'] == pulse
                       and target['direction'] == direction]
            if not matches:
                pulse_matches = [target for target in slam_targets
                                 if not target['assigned'] and target['pulse'] == pulse]
                if len(pulse_matches) == 1:
                    matches = pulse_matches
                    counts['spin_direction_mismatches'] = counts.get('spin_direction_mismatches', 0) + 1
                    camera_warnings.append(
                        f'{kind} direction {direction} differs from its only laser slam at {pulse}; '
                        'VOX follows the slam direction')
                else:
                    camera_unmapped.append(f'{kind} event has no matching laser slam: {event}')
                    counts['spin_events_unmapped'] = counts.get('spin_events_unmapped', 0) + 1
                    continue
            if len(matches) > 1:
                counts['spin_events_ambiguous'] = counts.get('spin_events_ambiguous', 0) + 1
            target = matches[0]
            roll_type, roll_length = roll_encoding(kind, length)
            fields = target['entry'][2]
            fields[3] = roll_type
            fields[9] = roll_length
            target['assigned'] = True
            counts[f'{kind}_events'] += 1
            end = max(end, pulse + length)

    if slam_events.get('swing'):
        camera_unmapped.append(f'{len(slam_events["swing"])} swing events have no exact VOX inverse')
        counts['swing_events_unmapped'] = len(slam_events['swing'])

    # Finalize laser text only after roll fields have been attached. Official
    # v12/v13 charts keep a matching copy in TRACK ORIGINAL L/R.
    for track in (1, 8):
        for pulse, serial, fields in laser_entries[track]:
            text = '\t'.join(map(str, fields))
            tracks[track].append((pulse, serial, text))
            original_lasers[track].append((pulse, serial, text))
    bpm_rows = []
    for event in beat.get('bpm', []):
        pulse, bpm = int(event[0]), float(event[1])
        if pulse % 5 or not math.isfinite(bpm) or bpm <= 0:
            raise ConversionError(f'Invalid/unrepresentable BPM event: {event}')
        bpm_rows.append(f'{timeline.position(pulse)}\t{bpm:.4f}\t4')
    if not bpm_rows or not bpm_rows[0].startswith('001,01,00'):
        raise ConversionError('An initial BPM event at pulse 0 is required')
    meter_rows = [f'{timeline.position(timeline.starts[i])}\t{n}\t{den}'
                  for i, (_, n, den) in enumerate(timeline.changes)]

    spcontroller = []

    # Initialize the normalized camera ranges before their value rows.
    for controller, anchors in CAMERA_REALIZE_ANCHORS.values():
        low, neutral, high = anchors
        spcontroller.append((
            0, len(spcontroller),
            f'001,01,00\tRealize\t{controller}\t0\t{low:.2f}\t{neutral:.2f}\t{high:.2f}\t0.00'))
    counts['camera_realize_rows'] = len(CAMERA_REALIZE_ANCHORS)

    # These initialize the arcade laser renderer's horizontal analog ranges.
    # They occur in every official chart;
    spcontroller.extend([
        (0, 2, '001,01,00\tAIRL_ScaX\t1\t0\t0.00\t1.00\t0.00\t0.00'),
        (0, 3, '001,01,00\tAIRR_ScaX\t1\t0\t0.00\t2.00\t0.00\t0.00'),
    ])
    counts['air_scale_rows'] = 2

    def add_sp_row(pulse, name, duration, start_value, end_value, node_type):
        nonlocal end
        if pulse % 5 or duration % 5:
            raise ConversionError(f'{name} event is outside VOX grid: {pulse}+{duration}')
        if abs(start_value) < 5e-13:
            start_value = 0.0
        if abs(end_value) < 5e-13:
            end_value = 0.0
        text = (f'{timeline.position(pulse)}\t{name}\t2\t{duration // 5}\t'
                f'{start_value:.9f}\t{end_value:.9f}\t{node_type}\t0.000000')
        spcontroller.append((pulse, len(spcontroller), text))
        end = max(end, pulse + duration)

    body = camera.get('cam', {}).get('body', {})
    for key, vox_name, scale in (
            ('zoom_bottom', 'CAM_Radi', zoom_bottom_scale),
            ('zoom_top', 'CAM_RotX', zoom_top_scale)):
        points = body.get(key, [])
        if not points:
            continue
        segments, jumps = sampled_graph_segments(points, curve_step)
        rows = [('jump', y, 0, v0, v1) for y, v0, v1 in jumps]
        rows += [('segment', y0, y1 - y0, v0, v1) for y0, y1, v0, v1 in segments]
        rows.sort(key=lambda row: (row[1], 0 if row[0] == 'jump' else 1))
        for i, (_, pulse, duration, start_value, end_value) in enumerate(rows):
            # C6 is a series-node field for Tilt only. Official CAM_RotX and
            # CAM_Radi rows keep it at zero throughout.
            add_sp_row(pulse, vox_name, duration,
                       start_value * scale,
                       end_value * scale, 0)
        counts['camera_rows'] += len(rows)
        counts[f'{key}_points'] = len(points)

    for key in ('zoom_side', 'rotation_deg', 'center_split'):
        if body.get(key):
            camera_unmapped.append(f'camera.cam.body.{key} is not mapped')

    tilt_mode_values = {'normal': 0, 'bigger': 1, 'keep_bigger': 2}
    tilt_mode_rows = []
    parsed_tilt = []

    def parse_tilt(point):
        if not isinstance(point, list) or len(point) != 2:
            raise ConversionError(f'Invalid tilt point: {point}')
        pulse, raw = int(point[0]), point[1]
        controls = (0.0, 0.0)
        if isinstance(raw, str):
            return pulse, raw, raw, controls
        if isinstance(raw, (int, float)):
            value = float(raw)
            return pulse, value, value, controls
        if not isinstance(raw, list) or len(raw) != 2:
            raise ConversionError(f'Invalid tilt value: {raw}')
        first, second = raw
        if isinstance(first, list):
            if (len(first) != 2
                    or not all(isinstance(value, (int, float)) for value in first)
                    or not isinstance(second, list) or len(second) != 2):
                raise ConversionError(f'Invalid tilt transition: {raw}')
            return pulse, float(first[0]), float(first[1]), tuple(map(float, second))
        if not isinstance(first, (int, float)):
            raise ConversionError(f'Invalid tilt value: {raw}')
        if isinstance(second, str):
            return pulse, float(first), second, controls
        if isinstance(second, list):
            if len(second) != 2:
                raise ConversionError(f'Invalid tilt curve: {raw}')
            return pulse, float(first), float(first), tuple(map(float, second))
        return pulse, float(first), float(second), controls

    for point in camera.get('tilt', []):
        parsed_tilt.append(parse_tilt(point))
    if any(parsed_tilt[i + 1][0] <= parsed_tilt[i][0] for i in range(len(parsed_tilt)-1)):
        raise ConversionError('Tilt pulses must be strictly increasing')
    for pulse, incoming, outgoing, controls in parsed_tilt:
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in controls):
            raise ConversionError(f'Invalid tilt curve controls at {pulse}: {controls}')
        for value in (incoming, outgoing):
            if isinstance(value, str):
                if value in tilt_mode_values:
                    tilt_mode_rows.append((pulse, tilt_mode_values[value]))
                elif value != 'zero':
                    camera_unmapped.append(f'unsupported automatic tilt mode {value!r} at {pulse}')
        if (isinstance(incoming, (int, float)) and isinstance(outgoing, (int, float))
                and incoming != outgoing):
            add_sp_row(pulse, 'Tilt', 0, incoming * tilt_scale, outgoing * tilt_scale, 0)
            counts['manual_tilt_rows'] += 1

    manual_segments = []
    for current, following in zip(parsed_tilt, parsed_tilt[1:]):
        pulse, _, outgoing, controls = current
        next_pulse, next_incoming, next_outgoing, _ = following
        if not isinstance(outgoing, (int, float)) or not isinstance(next_incoming, (int, float)):
            continue
        a, b = controls
        anchors = [(pulse, outgoing)]
        if abs(a - b) > 1e-12:
            for y in range(pulse + curve_step, next_pulse, curve_step):
                x = (y-pulse)/(next_pulse-pulse)
                anchors.append((y, outgoing+(next_incoming-outgoing)*curve(x, a, b)))
        anchors.append((next_pulse, next_incoming))
        ending_auto = isinstance(next_outgoing, str)
        for j, ((y0, v0), (y1, v1)) in enumerate(zip(anchors, anchors[1:])):
            manual_segments.append((y0, y1-y0, v0, v1,
                                    ending_auto and j == len(anchors)-2))
    for i, (pulse, duration, start_value, end_value, ending_auto) in enumerate(manual_segments):
        if len(manual_segments) == 1:
            node_type = 1 if ending_auto else 2
        else:
            node_type = 2 if i == 0 else 3 if ending_auto or i == len(manual_segments)-1 else 0
        add_sp_row(pulse, 'Tilt', duration, start_value * tilt_scale,
                   end_value * tilt_scale, node_type)
        counts['manual_tilt_rows'] += 1

    collapsed_modes = []
    for row in sorted(set(tilt_mode_rows)):
        if not collapsed_modes or row != collapsed_modes[-1]:
            collapsed_modes.append(row)
    if not collapsed_modes or collapsed_modes[0][0] != 0:
        collapsed_modes.insert(0, (0, 0))
    counts['auto_tilt_events'] = len(collapsed_modes)
    tilt_rows = [f'{timeline.position(pulse)}\t{mode}' for pulse, mode in collapsed_modes]
    spcontroller.sort(key=lambda row: row[:2])
    for values in tracks.values():
        values.sort(key=lambda row: row[:-1])
    header = '// Generated by kson_to_vox.py\n// Note and supported camera conversion; see adjacent report JSON.\n\n'
    chunks = [header, section('FORMAT VERSION', ['13']), section('BEAT INFO', meter_rows),
              section('BPM INFO', bpm_rows), section('TILT MODE INFO', tilt_rows),
              section('LYRIC INFO', []), section('END POSITION', [timeline.position(end)]),
              section('TAB EFFECT INFO', []), section('FXBUTTON EFFECT INFO', []),
              section('TAB PARAM ASSIGN INFO', []), section('REVERB EFFECT PARAM', [])]
    for track in range(1, 9):
        chunks.append(section(f'TRACK{track}', [row[-1] for row in tracks[track]]))
    chunks.extend([section('TRACK AUTO TAB', []),
                   section('TRACK ORIGINAL L', [row[-1] for row in original_lasers[1]]),
                   section('TRACK ORIGINAL R', [row[-1] for row in original_lasers[8]]),
                   section('SPCONTROLER', [row[-1] for row in spcontroller])])
    unsupported = [key for key in ('audio', 'bg', 'compat', 'editor', 'gauge') if key in chart]
    if camera_unmapped:
        unsupported.append('camera(partial)')
    report = {'kson_format_version': 1, 'vox_version': 13, 'end_pulse': end,
              'end_position': timeline.position(end), 'curve_step_pulses': curve_step,
              'camera_mapping': {
                  'realize_anchors': {name: list(anchors)
                                      for name, (_, anchors) in CAMERA_REALIZE_ANCHORS.items()},
                  'zoom_top_scale': zoom_top_scale,
                  'zoom_bottom_scale': zoom_bottom_scale,
                  'tilt_scale': tilt_scale,
              },
              'counts': counts, 'unmapped_top_level': unsupported,
              'camera_unmapped': camera_unmapped,
              'camera_warnings': camera_warnings,
              'warnings': ['FX audio effects, keysounds, unsupported camera fields, background and editor metadata are not converted.',
                           'Curved lasers are sampled every curve_step pulses; KSON curve controls are not retained analytically.',
                           'Curved camera and manual tilt graphs are sampled into linear SPCONTROLER spans.',
                           'TRACK ORIGINAL L/R mirror the expanded laser tracks so wide-range metadata remains available to game importers.',
                           'KSON metadata and BGM data have no standard native VOX chart mapping.']}
    return '\n'.join(chunks), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--curve-step', type=int, default=15,
                        help='KSON pulses between expanded curve samples (default 15; must be multiple of 5)')
    parser.add_argument('--zoom-top-scale', type=float, default=DEFAULT_ZOOM_TOP_SCALE,
                        help='CAM_RotX per KSON zoom_top unit with initialized Realize (default: 0.0013225)')
    parser.add_argument('--zoom-bottom-scale', type=float, default=DEFAULT_ZOOM_BOTTOM_SCALE,
                        help='CAM_Radi per KSON zoom_bottom unit with initialized Realize (default: -0.00382)')
    parser.add_argument('--tilt-scale', type=float, default=DEFAULT_TILT_SCALE,
                        help=f'VOX Tilt per KSON manual tilt unit (default: {DEFAULT_TILT_SCALE})')
    args = parser.parse_args()
    output = args.output or Path('output') / (args.source.stem+'.vox')
    try:
        chart = json.loads(args.source.read_text(encoding='utf-8-sig'))
        vox, report = convert_kson(chart, curve_step=args.curve_step,
                                   zoom_top_scale=args.zoom_top_scale,
                                   zoom_bottom_scale=args.zoom_bottom_scale,
                                   tilt_scale=args.tilt_scale)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(vox, encoding='utf-8', newline='\n')
        output.with_suffix('.report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8', newline='\n')
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        parser.exit(1, f'Conversion failed: {exc}\n')
    print(f'VOX: {output}\nReport: {output.with_suffix(".report.json")}')
    print(json.dumps(report['counts']))


if __name__ == '__main__':
    main()
