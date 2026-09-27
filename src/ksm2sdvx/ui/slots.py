"""Chart-slot choice with arrow-key operation in addition to the Fluent popup."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from qfluentwidgets import ComboBox

from ksm2sdvx.metadata.models import ChartSlot


class ChartSlotPicker(ComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.addItems([slot.value for slot in ChartSlot])
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Chart slot")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        keys: dict[int, int] = {
            Qt.Key.Key_Up: self.currentIndex() - 1,
            Qt.Key.Key_Down: self.currentIndex() + 1,
            Qt.Key.Key_Home: 0,
            Qt.Key.Key_End: len(ChartSlot) - 1,
        }
        if event.key() in keys:
            self.setCurrentIndex(max(0, min(len(ChartSlot) - 1, keys[event.key()])))
            event.accept()
        else:
            super().keyPressEvent(event)
