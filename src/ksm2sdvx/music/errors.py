"""Expected audio decoding, analysis, and encoding failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class MusicError(Ksm2SdvxError):
    """Audio could not be processed into the requested output."""
