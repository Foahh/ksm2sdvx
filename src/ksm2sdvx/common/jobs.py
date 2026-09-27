"""Cooperative job control, independent of presentation and worker implementation."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from ksm2sdvx.common.errors import Ksm2SdvxError


class JobCancelled(Ksm2SdvxError):
    """Preparation stopped at a boundary where installed files are unchanged."""


@dataclass(frozen=True, slots=True)
class Progress:
    stage: str
    completed: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class JobControl:
    cancelled: Event
    report: Callable[[Progress], None] = lambda _: None

    def checkpoint(self, stage: str, completed: int = 0, total: int = 0) -> None:
        if self.cancelled.is_set():
            raise JobCancelled("Cancelled; installed files were not changed")
        self.report(Progress(stage, completed, total))


def checkpoint(control: JobControl | None, stage: str, completed: int = 0, total: int = 0) -> None:
    if control is not None:
        control.checkpoint(stage, completed, total)
