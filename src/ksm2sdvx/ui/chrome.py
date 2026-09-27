"""Fluent menus and a quiet workspace footer, with desktop keyboard navigation."""

from functools import partial

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckableMenu,
    IndeterminateProgressBar,
    ProgressBar,
    RoundMenu,
    TransparentPushButton,
)


class MenuBar(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("menuStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(12, 4, 12, 4)
        self.row.setSpacing(2)
        self.row.addStretch()
        self.buttons: list[TransparentPushButton] = []
        self.menus: list[RoundMenu] = []

    def add_menu(self, title: str, mnemonic: str, *, checkable: bool = False) -> RoundMenu:
        button = TransparentPushButton(title, self)
        button.setAccessibleName(f"{title} menu")
        button.setFixedHeight(32)
        button.installEventFilter(self)
        menu = CheckableMenu(title, self) if checkable else RoundMenu(title, self)
        menu.setItemHeight(34)
        menu.installEventFilter(self)
        menu.view.installEventFilter(self)
        index = len(self.menus)
        button.clicked.connect(partial(self.open_menu, index))
        shortcut = QShortcut(QKeySequence(f"Alt+{mnemonic}"), self)
        shortcut.activated.connect(partial(self.open_menu, index))
        self.row.insertWidget(index, button)
        self.buttons.append(button)
        self.menus.append(menu)
        return menu

    def open_menu(self, index: int) -> None:
        for menu in self.menus:
            menu.close()
        menu, button = self.menus[index], self.buttons[index]
        menu.exec(button.mapToGlobal(QPoint(0, button.height())), ani=False)
        menu.view.setFocus(Qt.FocusReason.MenuBarFocusReason)
        for row in range(menu.view.count()):
            item = menu.view.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                menu.view.setCurrentRow(row)
                break

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        opened = next((i for i, menu in enumerate(self.menus) if menu.isVisible()), None)
        if event.type() == QEvent.Type.Enter and opened is not None:
            for index, button in enumerate(self.buttons):
                if watched is button and index != opened:
                    self.open_menu(index)
                    return True
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if opened is None:
                if (
                    event.key() == Qt.Key.Key_Down
                    and isinstance(watched, TransparentPushButton)
                    and watched in self.buttons
                ):
                    self.open_menu(self.buttons.index(watched))
                    return True
            else:
                menu = self.menus[opened]
                if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    delta = 1 if event.key() == Qt.Key.Key_Right else -1
                    self.open_menu((opened + delta) % len(self.menus))
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    menu.close()
                    self.buttons[opened].setFocus()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    item = menu.view.currentItem()
                    action: object = item.data(Qt.ItemDataRole.UserRole) if item else None
                    if isinstance(action, QAction) and action.isEnabled():
                        menu.close()
                        action.trigger()
                    return True
        return super().eventFilter(watched, event)


class JobProgress(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(3)
        self.pages = QStackedLayout(self)
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.determinate = ProgressBar()
        self.indeterminate = IndeterminateProgressBar(start=False)
        self.pages.addWidget(self.determinate)
        self.pages.addWidget(self.indeterminate)
        self.hide()

    def report(self, completed: int = 0, total: int = 0) -> None:
        self.show()
        if total:
            self.indeterminate.stop()
            self.pages.setCurrentWidget(self.determinate)
            self.determinate.setRange(0, total)
            self.determinate.setValue(completed)
        else:
            self.pages.setCurrentWidget(self.indeterminate)
            self.indeterminate.start()

    def finish(self) -> None:
        self.indeterminate.stop()
        self.hide()


class WorkspaceFooter(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("workspaceFooter")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.progress = JobProgress()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        row.setContentsMargins(20, 4, 20, 4)
        row.setSpacing(16)
        self.message = CaptionLabel()
        self.message.setObjectName("secondary")
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message.setMinimumHeight(28)
        row.addWidget(self.message, 1)
        self.counts = CaptionLabel()
        self.counts.setObjectName("secondary")
        row.addWidget(self.counts)
        self.cancel = TransparentPushButton("Cancel")
        self.cancel.setFixedHeight(28)
        self.cancel.hide()
        row.addWidget(self.cancel)
        layout.addLayout(row)

    def set_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setToolTip(text)
