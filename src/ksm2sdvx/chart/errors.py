"""Expected chart decoding, validation, and conversion failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class KsonDecodeError(Ksm2SdvxError):
    pass


class KsonValidationError(Ksm2SdvxError):
    def __init__(self, message: str, path: str = "") -> None:
        self.path = path
        super().__init__(f"{path or '/'}: {message}")


class UnsupportedFormatError(Ksm2SdvxError):
    pass


class ConversionError(Ksm2SdvxError):
    pass
