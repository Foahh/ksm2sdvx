"""Worker jobs send immutable values to GUI-thread slots."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal

from ksm2sdvx.common.jobs import JobCancelled, JobControl


@dataclass(frozen=True, slots=True)
class Outcome:
    value: object = None
    error: str = ""
    cancelled: bool = False


class Worker(QThread):
    result = Signal(object)
    progress = Signal(object)

    def __init__(self, operation: Callable[[JobControl], object], parent: QObject) -> None:
        super().__init__(parent)
        self.operation = operation
        self.cancelled = Event()

    def run(self) -> None:
        try:
            value = self.operation(JobControl(self.cancelled, self.progress.emit))
            result = Outcome(value)
        except JobCancelled as exc:
            result = Outcome(error=str(exc), cancelled=True)
        except Exception as exc:
            result = Outcome(error=f"{type(exc).__name__}: {exc}")
        self.result.emit(result)
