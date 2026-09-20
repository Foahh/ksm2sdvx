"""Exact meter arithmetic; text formatting belongs to the VOX serializer."""

from bisect import bisect_right
from fractions import Fraction

from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.kson.model import MeterEvent
from ksm2sdvx.chart.types import VoxTick
from ksm2sdvx.chart.vox.model import VoxPosition


def ticks(pulses: int) -> VoxTick:
    if type(pulses) is not int or pulses < 0 or pulses % 5:
        raise ConversionError(f"Pulse/duration {pulses} is outside the VOX five-pulse grid")
    return VoxTick(pulses // 5)


class Timeline:
    def __init__(self, changes: tuple[MeterEvent, ...]) -> None:
        self.changes = changes
        starts: list[Fraction] = []
        for i, event in enumerate(changes):
            if i == 0:
                starts.append(Fraction(0))
            else:
                previous = changes[i - 1]
                starts.append(
                    starts[-1]
                    + (event.measure - previous.measure)
                    * Fraction(960 * previous.numerator, previous.denominator)
                )
        self.starts = tuple(starts)

    def position(self, pulse: int | Fraction) -> VoxPosition:
        pulse = Fraction(pulse)
        if pulse < 0 or pulse.denominator != 1 or pulse % 5:
            raise ConversionError(f"Pulse {pulse} is outside the VOX five-pulse grid")
        i = bisect_right(self.starts, pulse) - 1
        if i < 0:
            raise ConversionError("Pulse precedes the chart")
        event = self.changes[i]
        measure_length = Fraction(960 * event.numerator, event.denominator)
        measure = event.measure + int((pulse - self.starts[i]) // measure_length)
        within = pulse - (self.starts[i] + (measure - event.measure) * measure_length)
        beat_length = Fraction(960, event.denominator)
        beat = int(within // beat_length) + 1
        tick = (within - (beat - 1) * beat_length) / 5
        if tick.denominator != 1:
            raise ConversionError(f"Pulse {pulse} cannot be represented within this VOX meter")
        return VoxPosition(measure + 1, beat, VoxTick(int(tick)))
