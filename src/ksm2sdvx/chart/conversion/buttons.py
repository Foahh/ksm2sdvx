from ksm2sdvx.chart.conversion.report import ReportBuilder
from ksm2sdvx.chart.conversion.timing import Timeline, ticks
from ksm2sdvx.chart.kson.model import NoteInfo
from ksm2sdvx.chart.vox.model import VoxBtNote, VoxFxChip, VoxFxHold, VoxTrack


def convert_buttons(
    notes: NoteInfo, timeline: Timeline, report: ReportBuilder
) -> tuple[tuple[VoxTrack, ...], int]:
    tracks: list[VoxTrack] = []
    end = 0
    for kind, numbers, lanes in (("bt", (3, 4, 5, 6), notes.bt), ("fx", (2, 7), notes.fx)):
        for number, lane in zip(numbers, lanes, strict=True):
            events: list[VoxBtNote | VoxFxChip | VoxFxHold] = []
            for note in lane:
                position = timeline.position(note.pulse)
                duration = ticks(note.duration)
                if kind == "bt":
                    events.append(VoxBtNote(position, duration, 2 if note.duration else 0))
                elif note.duration:
                    # The converter installs a no-effect pair at wire index 2.
                    events.append(VoxFxHold(position, duration, 2))
                else:
                    events.append(VoxFxChip(position))
                end = max(end, note.pulse + note.duration)
                report.count(kind)
            tracks.append(VoxTrack(number, tuple(events)))
    return tuple(tracks), end
