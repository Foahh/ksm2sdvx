"""Public jacket processing operations and contracts."""

from ksm2sdvx.jacket.application import convert_jacket_file
from ksm2sdvx.jacket.errors import JacketError
from ksm2sdvx.jacket.interfaces import JacketProcessor
from ksm2sdvx.jacket.models import (
    JacketRequest,
    JacketResult,
    JacketSettings,
    JacketSize,
)
from ksm2sdvx.jacket.processor import FfmpegJacketProcessor

__all__ = [
    "FfmpegJacketProcessor",
    "JacketError",
    "JacketProcessor",
    "JacketRequest",
    "JacketResult",
    "JacketSettings",
    "JacketSize",
    "convert_jacket_file",
]
