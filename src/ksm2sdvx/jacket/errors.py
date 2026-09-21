"""Expected artwork processing failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class JacketError(Ksm2SdvxError):
    """Artwork could not be decoded, transformed, or written."""
