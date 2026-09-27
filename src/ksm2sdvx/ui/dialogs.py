"""Fluent modal dialogs for explicit preparation and publication choices."""

from pathlib import Path

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    DoubleSpinBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.application import ToolPaths
from ksm2sdvx.packs.models import ChangePlan, Recovery
from ksm2sdvx.pipeline.config import ChartInput, PackageConfig
from ksm2sdvx.ui.slots import ChartSlotPicker


class ReviewDialog(QDialog):
    def __init__(self, plan: ChangePlan, warnings: tuple[str, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Review — {plan.pack_name}")
        self.resize(780, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(SubtitleLabel(self.windowTitle()))
        layout.addWidget(
            BodyLabel("Review the staged changes before writing to the selected song pack.")
        )
        detail = PlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText("\n".join((*plan.summary, "", *warnings)))
        layout.addWidget(detail)
        table = TableWidget()
        table.setColumnCount(2)
        table.setRowCount(len(plan.changes))
        table.verticalHeader().hide()
        table.setHorizontalHeaderLabels(["Operation", "File"])
        table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        for row, change in enumerate(plan.changes):
            operation = (
                "Remove" if change.after is None else "Add" if change.before is None else "Replace"
            )
            table.setItem(row, 0, QTableWidgetItem(operation))
            table.setItem(row, 1, QTableWidgetItem(change.relative))
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        closed = CheckBox("The game is closed. Apply these changes.")
        layout.addWidget(closed)
        layout.addWidget(
            BodyLabel(
                "Changed files are backed up. Recovery can restore the latest apply for this pack."
            )
        )
        buttons = QDialogButtonBox()
        apply = PrimaryPushButton("Apply changes")
        apply.setObjectName("applyChanges")
        buttons.addButton(apply, QDialogButtonBox.ButtonRole.ApplyRole)
        buttons.addButton(PushButton("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        apply.setEnabled(False)
        closed.toggled.connect(apply.setEnabled)
        apply.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class KsonDialog(QDialog):
    def __init__(self, song_id: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.song_id = song_id
        self.config: PackageConfig | None = None
        self.paths: list[Path] = []
        self.slots: list[ChartSlotPicker] = []
        self.levels: list[DoubleSpinBox] = []
        self.setWindowTitle("Import KSON song")
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(SubtitleLabel(self.windowTitle()))
        form = QFormLayout()
        self.root = LineEdit()
        browse = PushButton("Browse…")
        browse.clicked.connect(self.choose_root)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root)
        root_row.addWidget(browse)
        form.addRow("Source folder", root_row)
        self.name = LineEdit()
        self.title = LineEdit()
        self.artist = LineEdit()
        form.addRow("Reserved song ID", BodyLabel(str(song_id)))
        form.addRow("Asset name (ASCII)", self.name)
        form.addRow("Title override (optional)", self.title)
        form.addRow("Artist override (optional)", self.artist)
        layout.addLayout(form)
        label = BodyLabel(
            "Group charts for one song and assign each slot explicitly. Music and preview timing come from KSON.\nLeave level at Source to use the chart's level. Levels entered here use tenths."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = TableWidget()
        self.table.setColumnCount(3)
        self.table.verticalHeader().hide()
        self.table.setHorizontalHeaderLabels(["KSON chart", "Slot", "Level"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 130)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setMinimumHeight(180)
        layout.addWidget(self.table)
        add = PushButton("Add charts…")
        add.clicked.connect(self.add_charts)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox()
        buttons.addButton(PrimaryPushButton("OK"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(PushButton("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.prepare)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select the source song folder", self.root.text()
        )
        if folder:
            self.root.setText(folder)

    def add_charts(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, "Select KSON charts for this song", self.root.text(), "KSON charts (*.kson)"
        )
        for name in names:
            path = Path(name)
            if path in self.paths:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.table.setItem(row, 0, item)
            slot = ChartSlotPicker()
            slot.setCurrentIndex(min(row, len(ChartSlot) - 1))
            level = DoubleSpinBox()
            level.setLocale(QLocale.c())
            level.setRange(-0.1, 25.5)
            level.setDecimals(1)
            level.setSingleStep(0.1)
            level.setSpecialValueText("Source")
            level.setValue(-0.1)
            self.table.setCellWidget(row, 1, slot)
            self.table.setCellWidget(row, 2, level)
            self.paths.append(path)
            self.slots.append(slot)
            self.levels.append(level)

    def prepare(self) -> None:
        root = Path(self.root.text()).absolute()
        assignments = [slot.currentText() for slot in self.slots]
        if not self.root.text() or not self.paths or not self.name.text():
            QMessageBox.warning(
                self,
                "Incomplete song",
                "Choose a source folder, an asset name and at least one chart.",
            )
            return
        if len(set(assignments)) != len(assignments):
            QMessageBox.warning(self, "Duplicate slot", "Assign each target slot only once.")
            return
        if any(not path.is_relative_to(root) for path in self.paths):
            QMessageBox.warning(
                self,
                "Source folder",
                "All charts and their resources must be inside the source folder.",
            )
            return
        self.config = PackageConfig(
            self.name.text(),
            root,
            self.song_id,
            tuple(
                ChartInput(
                    path,
                    slot.currentText(),
                    level_tenths=None if level.value() < 0 else round(level.value() * 10),
                )
                for path, slot, level in zip(self.paths, self.slots, self.levels, strict=True)
            ),
            title=self.title.text() or None,
            artist=self.artist.text() or None,
        )
        self.accept()


class ToolsDialog(QDialog):
    def __init__(self, tools: ToolPaths, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tool locations")
        self.resize(620, 200)
        layout = QFormLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setVerticalSpacing(16)
        layout.addRow(SubtitleLabel("Media tools"))
        self.ffmpeg = LineEdit()
        self.ffmpeg.setText(tools.ffmpeg)
        self.ffprobe = LineEdit()
        self.ffprobe.setText(tools.ffprobe)
        layout.addRow("FFmpeg", self.ffmpeg)
        layout.addRow("FFprobe", self.ffprobe)
        buttons = QDialogButtonBox()
        buttons.addButton(PrimaryPushButton("OK"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(PushButton("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class RecoveryDialog(QDialog):
    def __init__(self, records: tuple[Recovery, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workspace Recovery")
        self.resize(660, 350)
        self.transaction = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(SubtitleLabel(self.windowTitle()))
        layout.addWidget(
            BodyLabel(
                "Restore the latest apply, including removed packs. External changes block restoration."
            )
        )
        self.table = TableWidget()
        self.table.setColumnCount(3)
        self.table.setRowCount(len(records))
        self.table.verticalHeader().hide()
        self.table.setHorizontalHeaderLabels(["Song pack", "State", "Changes"])
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.records = records
        for row, record in enumerate(records):
            for column, text in enumerate((record.pack_name, record.status, record.description)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        layout.addWidget(self.table)
        closed = CheckBox("The game is closed.")
        layout.addWidget(closed)
        restore = PrimaryPushButton("Restore selected apply")
        restore.setEnabled(False)
        closed.toggled.connect(restore.setEnabled)
        restore.clicked.connect(self.restore)
        layout.addWidget(restore)
        close = QDialogButtonBox()
        close.addButton(PushButton("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def restore(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.transaction = self.records[row].transaction
            self.accept()
