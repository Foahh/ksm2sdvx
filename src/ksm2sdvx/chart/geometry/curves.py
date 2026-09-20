"""Quadratic Bezier evaluation and deterministic linear sampling."""

import math

from ksm2sdvx.chart.kson.model import CurveControl


def parameter(x: float, a: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    return x / (a + math.sqrt(max(0.0, a * a + (1 - 2 * a) * x)))


def curve(x: float, a: float, b: float) -> float:
    u = parameter(x, a)
    return 2 * b * u * (1 - u) + u * u


def anchors(
    start: int, stop: int, outgoing: float, incoming: float, control: CurveControl, step: int
) -> tuple[tuple[int, float], ...]:
    if step <= 0 or stop <= start:
        raise ValueError("Sampling requires a positive step and increasing endpoints")
    result = [(start, outgoing)]
    if control.curved:
        result.extend(
            (
                pulse,
                outgoing
                + (incoming - outgoing)
                * curve((pulse - start) / (stop - start), control.x, control.y),
            )
            for pulse in range(start + step, stop, step)
        )
    result.append((stop, incoming))
    return tuple(result)
