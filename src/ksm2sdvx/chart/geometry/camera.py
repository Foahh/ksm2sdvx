"""Joint zoom projection and VOX camera normalization.

Source projection adapted from https://github.com/kshootmania/ksm-v2.
Copyright notices and permission are distributed in LICENSES/ksm-v2.txt.
"""

from dataclasses import dataclass
from math import asin, atan2, cos, hypot, isfinite, pi, sin, sqrt, tan
from struct import pack, unpack

from ksm2sdvx.chart.errors import ConversionError

MANUAL_TILT_SCALE = -8 / 19
PROJECTION_TOLERANCE = 0.25


def _float32(value: float) -> float:
    try:
        return float(unpack("<f", pack("<f", value))[0])
    except (OverflowError, ValueError) as error:
        raise ConversionError("Camera value exceeds the source projection range") from error


@dataclass(frozen=True, slots=True)
class Normalization:
    low: float
    middle: float
    high: float

    @property
    def quadratic(self) -> float:
        return (self.low + self.high) / 2 - self.middle

    @property
    def linear(self) -> float:
        return (self.high - self.low) / 2

    def decode(self, value: float) -> float:
        return (self.quadratic * value + self.linear) * value + self.middle

    def encode(self, value: float) -> float:
        delta = value - self.middle
        if not isfinite(delta) or self.linear <= 0:
            raise ConversionError("Invalid camera normalization")
        if abs(self.quadratic) < 1e-14:
            return delta / self.linear
        discriminant = self.linear**2 + 4 * self.quadratic * delta
        if not isfinite(discriminant) or discriminant <= 1e-12:
            raise ConversionError("Camera value is outside the increasing normalization branch")
        return 2 * delta / (self.linear + sqrt(discriminant))


_HEIGHT = _float32(936 * 13 / 20)
_WIDTH = _float32(304 * 2 / 13)
_BELOW = _float32(_HEIGHT * 14 / 1024)
_ABOVE = _float32(_HEIGHT - _BELOW)
_SOURCE_FOCAL = 540 / tan(pi / 8)
_TARGET_FOCAL = 480 / tan(_float32(1.0245083570480347) / 2)
_TARGET_LENGTH = 755.0
_TARGET_HALF_WIDTH = 30.5


def _project(y: float, z: float) -> tuple[float, float]:
    depth = -(y - 45) * sin(pi / 12) + (z + 366) * cos(pi / 12)
    if not isfinite(depth) or depth <= 0:
        raise ConversionError("Camera geometry crosses the source camera plane")
    return (
        _SOURCE_FOCAL * _WIDTH / depth,
        540 - _SOURCE_FOCAL * ((y - 45) * cos(pi / 12) + (z + 366) * sin(pi / 12)) / depth,
    )


_JUDGMENT_Y = _project(2.6, -_HEIGHT / 2 - 0.4)[1]


def source_landmarks(bottom: float, top: float) -> tuple[float, float]:
    """Return untilted lane width at the judgment row and visible lane height."""
    if not isfinite(bottom) or not isfinite(top):
        raise ConversionError("Camera values must be finite")
    angle = _float32(top * (pi / 1200))
    if not isfinite(angle):
        raise ConversionError("Camera angle exceeds the source projection range")
    if 120 <= int((angle * 180 / pi) % 360) < 300:
        raise ConversionError("Reversed source camera geometry is not representable")
    s, c = _float32(sin(angle)), _float32(cos(angle))
    scaled = _float32(bottom / (450 if bottom > 0 else 180))
    far_width, far_y = _project(_ABOVE * s / 2.5, -_ABOVE / 2 + _ABOVE * c)
    near_width, near_y = _project(
        -scaled * 100 * sin(_float32(-0.6125)) * _HEIGHT / _ABOVE - _BELOW * s / 2.5,
        -_ABOVE / 2 - _BELOW * c / 2 - scaled * 100 * cos(_float32(-0.6125)) * _HEIGHT / _ABOVE,
    )
    if near_y == far_y:
        raise ConversionError("Camera side edges are horizontal")
    fraction = (_JUDGMENT_Y - far_y) / (near_y - far_y)
    if not 0 <= fraction <= 1 or far_y >= _JUDGMENT_Y:
        raise ConversionError("Camera judgment row is outside the upright lane geometry")
    return far_width + (near_width - far_width) * fraction, _JUDGMENT_Y - far_y


_SOURCE_NEUTRAL = source_landmarks(0, 0)


def target_landmarks(radius: float, pitch: float) -> tuple[float, float]:
    far_depth = radius + _TARGET_LENGTH * cos(pitch)
    if not all(isfinite(v) and 1 < v < 5000 for v in (radius, far_depth)):
        raise ConversionError("Camera geometry crosses a target clip plane")
    return (
        2 * _TARGET_FOCAL * _TARGET_HALF_WIDTH / radius,
        _TARGET_FOCAL * _TARGET_LENGTH * sin(pitch) / far_depth,
    )


@dataclass(frozen=True, slots=True)
class CameraPose:
    radius: float
    pitch: float
    width: float
    height: float


def zoom_pose(
    bottom: float, top: float, radius: Normalization, rotation: Normalization
) -> CameraPose:
    source_width, source_height = source_landmarks(bottom, top)
    neutral_width, neutral_height = target_landmarks(radius.middle, rotation.middle)
    width = neutral_width * source_width / _SOURCE_NEUTRAL[0]
    height = neutral_height * source_height / _SOURCE_NEUTRAL[1]
    distance = radius.middle * _SOURCE_NEUTRAL[0] / source_width
    sine = height * distance / (_TARGET_LENGTH * hypot(_TARGET_FOCAL, height))
    if abs(sine) >= 1:
        raise ConversionError("Camera height cannot be represented on the upright pitch branch")
    pitch = atan2(height, _TARGET_FOCAL) + asin(sine)
    radius.encode(distance)
    rotation.encode(pitch)
    target_landmarks(distance, pitch)
    return CameraPose(distance, pitch, width, height)


def projection_error(
    start: CameraPose, end: CameraPose, wanted: CameraPose, amount: float
) -> float:
    width, height = target_landmarks(
        start.radius + amount * (end.radius - start.radius),
        start.pitch + amount * (end.pitch - start.pitch),
    )
    return max(abs(width - wanted.width), abs(height - wanted.height))
