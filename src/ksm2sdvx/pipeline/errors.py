"""Package configuration and assembly failures."""

from ksm2sdvx.common.errors import Ksm2SdvxError


class PackageError(Ksm2SdvxError):
    """A package cannot be assembled from the supplied inputs."""
