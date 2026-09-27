"""Expected song-pack management failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class PackError(Ksm2SdvxError):
    """A workspace operation cannot be completed without user intervention."""
