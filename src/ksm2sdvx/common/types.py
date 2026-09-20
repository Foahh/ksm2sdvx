"""Shared time units and immutable JSON extension values."""

from collections.abc import Mapping
from typing import NewType

Milliseconds = NewType("Milliseconds", int)

type JsonValue = str | int | float | bool | None | tuple[JsonValue, ...] | Mapping[str, JsonValue]


def json_ready(value: JsonValue) -> object:
    """Thaw immutable extension data for the standard JSON encoder."""
    if isinstance(value, Mapping):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    return value
