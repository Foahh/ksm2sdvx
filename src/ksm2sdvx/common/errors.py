"""Expected failures at application boundaries."""


class Ksm2SdvxError(Exception):
    """Base class for failures suitable for a concise CLI message."""


class OutputError(Ksm2SdvxError):
    """An output could not be written."""
