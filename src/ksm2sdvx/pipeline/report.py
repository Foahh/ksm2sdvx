"""Versioned JSON representation of an inspection, including retained source models."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from ksm2sdvx.common.types import JsonValue
from ksm2sdvx.pipeline.models import PackageInspection


def _model_json(value: object) -> JsonValue:
    """Output adapter for this package's immutable dataclass tree."""
    if isinstance(value, Enum):
        return _model_json(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _model_json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return tuple(_model_json(item) for item in cast(tuple[object, ...], value))
    if isinstance(value, Mapping):
        return {key: _model_json(item) for key, item in cast(Mapping[str, object], value).items()}
    raise TypeError(f"Unsupported inspection value: {type(value).__name__}")


def inspection_to_dict(inspection: PackageInspection) -> dict[str, JsonValue]:
    return {
        "schema_version": inspection.schema_version,
        "valid": inspection.valid,
        "root": str(inspection.root),
        "charts": _model_json(inspection.charts),
        "assets": _model_json(inspection.assets),
        "diagnostics": tuple(d.to_dict() for d in inspection.diagnostics),
    }
