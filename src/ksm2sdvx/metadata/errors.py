"""Expected metadata decoding and conversion failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class MetadataError(Ksm2SdvxError):
    """Source metadata or target database settings cannot produce a valid entry."""
