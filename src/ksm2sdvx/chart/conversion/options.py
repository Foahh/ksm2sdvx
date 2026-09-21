from dataclasses import dataclass

from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.common.types import JsonValue


@dataclass(frozen=True, slots=True)
class ConversionOptions:
    curve_step: int = 15
    strict: bool = False

    def validate(self) -> None:
        if type(self.curve_step) is not int or self.curve_step <= 0 or self.curve_step % 5:
            raise ConversionError("curve_step must be a positive multiple of 5 KSON pulses")
        if type(self.strict) is not bool:
            raise ConversionError("strict must be boolean")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "curve_step": self.curve_step,
            "strict": self.strict,
        }
