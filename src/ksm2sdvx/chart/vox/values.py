"""Shared runtime checks for target values and safe text fields."""

import math

from ksm2sdvx.chart.errors import ConversionError


def integer(value: object, minimum: int | None = 0) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ConversionError(f"Expected VOX integer >= {minimum}: {value!r}")
    return value


def finite(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConversionError("VOX values must be finite numbers")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ConversionError("VOX values must be finite numbers")


def text_field(value: str) -> None:
    if not value or any(c in value for c in "\r\n\t\x00#") or "//" in value:
        raise ConversionError("VOX fields cannot be empty or contain section/comment delimiters")


def field(value: str | int | float) -> str:
    if isinstance(value, str):
        text_field(value)
        return value
    finite(value)
    return str(value)
