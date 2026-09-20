import math
from dataclasses import dataclass

from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.common.types import JsonValue


@dataclass(frozen=True, slots=True)
class ConversionOptions:
    curve_step: int = 15
    strict: bool = False
    zoom_top_scale: float = 0.0013225
    zoom_bottom_scale: float = -0.00382
    tilt_scale: float = -0.4217946006575624

    def validate(self) -> None:
        if type(self.curve_step) is not int or self.curve_step <= 0 or self.curve_step % 5:
            raise ConversionError("curve_step must be a positive multiple of 5 KSON pulses")
        if type(self.strict) is not bool:
            raise ConversionError("strict must be boolean")
        for value in (self.zoom_top_scale, self.zoom_bottom_scale, self.tilt_scale):
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if not valid:
                raise ConversionError("Camera scales must be finite numbers")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "curve_step": self.curve_step,
            "strict": self.strict,
            "zoom_top_scale": self.zoom_top_scale,
            "zoom_bottom_scale": self.zoom_bottom_scale,
            "tilt_scale": self.tilt_scale,
        }
