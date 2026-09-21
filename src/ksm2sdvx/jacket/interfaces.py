"""Contract for jacket processing implementations."""

from typing import Protocol

from ksm2sdvx.jacket.models import JacketRequest, JacketResult


class JacketProcessor[SettingsT](Protocol):
    def process(self, request: JacketRequest[SettingsT]) -> JacketResult:
        """Produce the requested file or raise Ksm2SdvxError; never return a skipped success."""
        ...
