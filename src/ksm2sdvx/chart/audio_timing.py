"""Exact pulse-to-sample conversion and tempo-aware effect trigger scheduling."""

from bisect import bisect_right
from fractions import Fraction

from ksm2sdvx.chart.conversion.timing import Timeline
from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.kson.model import EffectDefinition, EffectGroup, KsonChart


class AudioClock:
    def __init__(self, chart: KsonChart, sample_rate: int) -> None:
        self.tempos = chart.beat.bpm
        self.rate = sample_rate
        self.pulses = tuple(e.pulse for e in self.tempos)
        seconds = [Fraction(0)]
        for previous, event in zip(self.tempos, self.tempos[1:], strict=False):
            seconds.append(
                seconds[-1]
                + Fraction(event.pulse - previous.pulse, 4) / Fraction(str(previous.bpm))
            )
        self.seconds = tuple(seconds)
        self.meters = Timeline(chart.beat.time_signatures)

    def frame(self, pulse: int | Fraction) -> int:
        index = bisect_right(self.pulses, pulse) - 1
        seconds = self.seconds[index] + (Fraction(pulse) - self.pulses[index]) / (
            4 * Fraction(str(self.tempos[index].bpm))
        )
        return round(seconds * self.rate)

    def pulse(self, frame: int) -> Fraction:
        seconds = Fraction(frame, self.rate)
        index = bisect_right(self.seconds, seconds) - 1
        return self.pulses[index] + (seconds - self.seconds[index]) * 4 * Fraction(
            str(self.tempos[index].bpm)
        )

    def measures(self, end: Fraction) -> tuple[Fraction, ...]:
        result = [Fraction(0)]
        measure = 0
        while result[-1] <= end:
            index = bisect_right(tuple(e.measure for e in self.meters.changes), measure) - 1
            meter = self.meters.changes[index]
            result.append(result[-1] + Fraction(960 * meter.numerator, meter.denominator))
            measure += 1
        return tuple(result)


def _period(value: str) -> Fraction:
    # Scheduling uses OnMin; the DSP retains and interprets the complete value set.
    token = value.split(">", 1)[-1].split("-", 1)[0].strip()
    try:
        period = Fraction(token)
    except (ValueError, ZeroDivisionError) as exc:
        raise ConversionError(f"Invalid effect trigger period: {value!r}") from exc
    if period < 0:
        raise ConversionError(f"Effect trigger period must be nonnegative: {value!r}")
    return period


def _count(pulse: Fraction, period: Fraction, measures: tuple[Fraction, ...]) -> int:
    if period <= 0:
        return 0
    index = max(0, min(len(measures) - 2, bisect_right(measures, pulse) - 1))
    if period >= 1:
        return int(
            (index + (pulse - measures[index]) / (measures[index + 1] - measures[index])) // period
        )
    step = int(960 * period)
    return int((pulse - measures[index]) // step) if step else 0


def effect_triggers(
    definition: EffectDefinition, group: EffectGroup, clock: AudioClock, end_frame: int
) -> tuple[int, ...]:
    measures = clock.measures(clock.pulse(end_frame))
    if definition.kind in ("gate", "wobble"):
        return tuple(clock.frame(p) for p in measures[:-1])
    if definition.kind not in ("retrigger", "echo", "sidechain"):
        return ()
    key = "period" if definition.kind == "sidechain" else "update_period"
    default = {"retrigger": "1/2", "echo": "0", "sidechain": "1/4"}[definition.kind]
    periods = {Fraction(0): _period(dict(definition.parameters).get(key, default))}
    for event in group.changes:
        if event.effect == definition.name and event.parameter == key:
            periods[Fraction(event.pulse)] = _period(event.value)
    regions = sorted(periods.items())
    triggers: set[int] = set()
    for index, (start, period) in enumerate(regions):
        stop = regions[index + 1][0] if index + 1 < len(regions) else measures[-1]
        if period <= 0 or (period < 1 and int(960 * period) == 0):
            continue
        if index and _count(start - 1, regions[index - 1][1], measures) != _count(
            start, period, measures
        ):
            triggers.add(clock.frame(start))
        if period >= 1:
            measure_value = Fraction(0)
            while measure_value < len(measures) - 1:
                i = int(measure_value)
                pulse = measures[i] + (measure_value - i) * (measures[i + 1] - measures[i])
                if start <= pulse < stop:
                    triggers.add(clock.frame(pulse))
                measure_value += period
        else:
            for left, right in zip(measures, measures[1:], strict=False):
                pulse = left
                while pulse < right:
                    if start <= pulse < stop:
                        triggers.add(clock.frame(pulse))
                    pulse += int(960 * period)
    if definition.kind in ("retrigger", "echo"):
        triggers.update(
            clock.frame(e.pulse)
            for e in group.changes
            if e.effect == definition.name
            and e.parameter == "update_trigger"
            and e.value.split(">", 1)[0].split("-", 1)[0].strip() == "on"
        )
    return tuple(sorted(triggers))
