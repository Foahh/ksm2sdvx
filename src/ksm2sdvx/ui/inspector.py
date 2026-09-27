"""Desktop details editor; requests edits without mutating domain snapshots."""

from collections import Counter
from contextlib import suppress
from functools import partial
from typing import cast

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PlainTextEdit,
    ScrollArea,
    SegmentedWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TransparentPushButton,
)

from ksm2sdvx.metadata.models import ChartSlot
from ksm2sdvx.packs.database import CHART_FIELDS, SONG_FIELDS, FieldSpec
from ksm2sdvx.packs.models import Asset, Song
from ksm2sdvx.ui.slots import ChartSlotPicker


class Inspector(QWidget):
    edited = Signal(int, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel("Song details"))
        self.tabs = SegmentedWidget()
        self.pages = QStackedWidget()
        layout.addWidget(self.tabs)
        layout.addWidget(self.pages, 1)
        self.metadata = ScrollArea()
        self.metadata.setWidgetResizable(True)
        self.charts = ScrollArea()
        self.charts.setWidgetResizable(True)
        self.asset_table = TableWidget()
        self.asset_table.setColumnCount(3)
        self.asset_table.verticalHeader().hide()
        self.asset_table.setWordWrap(False)
        self.asset_table.setHorizontalHeaderLabels(["Asset", "State", "Used by"])
        self.asset_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.asset_table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.asset_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.asset_table.horizontalHeader().setStretchLastSection(True)
        self.problems = PlainTextEdit()
        self.problems.setReadOnly(True)
        self.tab_pages = {
            "Metadata": self.metadata,
            "Charts": self.charts,
            "Assets": self.asset_table,
            "Problems": self.problems,
        }
        for name, page in self.tab_pages.items():
            self.pages.addWidget(page)
            self.tabs.addItem(name, name)
        self.tabs.currentItemChanged.connect(self.select_tab)
        self.tabs.setCurrentItem("Metadata")
        self.song: Song | None = None
        self.readonly = True
        self.assets: tuple[Asset, ...] = ()
        self.preview = QLabel()
        self.title_label: SubtitleLabel | None = None
        self.summary_label: CaptionLabel | None = None

    def select_tab(self, name: str) -> None:
        self.pages.setCurrentWidget(self.tab_pages[name])

    def update_summary(self, song: Song) -> None:
        if self.title_label is not None and self.summary_label is not None:
            self.title_label.setText(song.title)
            self.summary_label.setText(f"{song.artist}\n\n{song.stem}")

    def _emit_text(self, editor: QLineEdit, song: Song, path: str) -> None:
        if editor.isModified():
            editor.setModified(False)
            self.edited.emit(song.index, path, editor.text())

    def _emit_number(self, editor: QSpinBox, song: Song, path: str) -> None:
        if str(editor.value()) != str(int(song.value(path))):
            self.edited.emit(song.index, path, str(editor.value()))

    def _field(self, song: Song, spec: FieldSpec, path: str, form: QFormLayout) -> None:
        values = [v for p, v in song.fields if p == path]
        if not values:
            return
        value = values[0]
        readonly = (
            self.readonly
            or len(values) != 1
            or path in song.readonly_fields
            or path.endswith("/jacket_print")
        )
        numeric = False
        with suppress(ValueError):
            numeric = (
                spec.minimum is not None
                and spec.maximum is not None
                and -(2**31) <= spec.minimum <= int(value) <= spec.maximum <= 2**31 - 1
            )
        if numeric and spec.minimum is not None and spec.maximum is not None:
            spin = SpinBox()
            spin.setLocale(QLocale.c())
            spin.setRange(spec.minimum, spec.maximum)
            spin.setValue(int(value))
            spin.setReadOnly(readonly)
            spin.setKeyboardTracking(False)
            spin.editingFinished.connect(partial(self._emit_number, spin, song, path))
            widget = spin
        else:
            text = LineEdit()
            text.setText(value)
            text.setReadOnly(readonly)
            text.editingFinished.connect(partial(self._emit_text, text, song, path))
            widget = text
        widget.setObjectName(path)
        widget.setToolTip(f"{path}\nStored value: {value}" + ("\nRead-only" if readonly else ""))
        label = BodyLabel(spec.label)
        label.setBuddy(widget)
        form.addRow(label, widget)

    @staticmethod
    def _replace(scroll: QScrollArea, widget: QWidget) -> None:
        previous = cast(QWidget | None, scroll.takeWidget())
        if previous is not None:
            previous.deleteLater()
        scroll.setWidget(widget)

    def show_song(
        self,
        song: Song | None,
        readonly: bool,
        assets: tuple[Asset, ...],
        problems: tuple[str, ...],
        jacket: bytes = b"",
    ) -> None:
        self.song, self.readonly, self.assets = song, readonly, assets
        self.title_label = None
        self.summary_label = None
        widget = QWidget()
        widget.setObjectName("inspectorPage")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 8, 8)
        layout.setSpacing(14)
        if song is not None:
            heading = SubtitleLabel(song.title)
            self.title_label = heading
            heading.setWordWrap(True)
            layout.addWidget(heading)
            identity = CaptionLabel(
                f"ID {song.song_id}  •  " + ("Read-only" if readonly else "Editable song")
            )
            identity.setObjectName("secondary")
            layout.addWidget(identity)
            summary = QHBoxLayout()
            preview = QLabel("No jacket preview")
            self.preview = preview
            preview.setObjectName("jacketPreview")
            preview.setFixedSize(112, 112)
            preview.setWordWrap(True)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if jacket:
                pixmap = QPixmap()
                if pixmap.loadFromData(jacket):
                    preview.setPixmap(
                        pixmap.scaled(
                            112,
                            112,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            summary.addWidget(preview)
            caption = CaptionLabel(f"{song.artist}\n\n{song.stem}")
            self.summary_label = caption
            caption.setObjectName("secondary")
            caption.setWordWrap(True)
            caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            summary.addWidget(caption, 1)
            layout.addLayout(summary)
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setVerticalSpacing(10)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            advanced_form = QFormLayout()
            advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for spec in SONG_FIELDS:
                self._field(song, spec, spec.path, advanced_form if spec.advanced else form)
            layout.addLayout(form)
            advanced = QWidget()
            advanced.setLayout(advanced_form)
            advanced.hide()
            toggle = TransparentPushButton()
            toggle.setText("Advanced  ▸")
            toggle.setCheckable(True)
            toggle.toggled.connect(advanced.setVisible)
            toggle.toggled.connect(
                lambda: toggle.setText("Advanced  ▾" if toggle.isChecked() else "Advanced  ▸")
            )
            layout.addWidget(toggle)
            layout.addWidget(advanced)
            raw = PlainTextEdit()
            raw.setReadOnly(True)
            raw.setPlainText("\n".join(f"{path} = {value}" for path, value in song.fields))
            raw.setMaximumHeight(160)
            raw.setToolTip(
                "All stored fields, including unknown and ambiguous values. These values are preserved."
            )
            advanced_form.addRow("Stored fields", raw)
        else:
            layout.addWidget(BodyLabel("Select a song to view its details."))
        layout.addStretch()
        self._replace(self.metadata, widget)
        charts = QWidget()
        charts.setObjectName("inspectorPage")
        chart_layout = QVBoxLayout(charts)
        if song is not None:
            slots = ChartSlotPicker()
            chart_layout.addWidget(slots)
            chart_forms = QStackedWidget()
            for slot in ChartSlot:
                fields = QWidget()
                form = QFormLayout(fields)
                form.setContentsMargins(0, 8, 0, 8)
                form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                for spec in CHART_FIELDS:
                    self._field(song, spec, f"difficulty/{slot.value}/{spec.path}", form)
                chart_forms.addWidget(fields)
            slots.currentIndexChanged.connect(chart_forms.setCurrentIndex)
            chart_layout.addWidget(chart_forms)
            hint = CaptionLabel(
                "Level uses the stored database value. Asset and song identities are fixed."
            )
            hint.setObjectName("secondary")
            hint.setWordWrap(True)
            chart_layout.addWidget(hint)
        self._replace(self.charts, charts)
        self.asset_table.setRowCount(len(assets))
        for row, asset in enumerate(assets):
            for column, value in enumerate(
                (
                    asset.relative,
                    "Loose file" if asset.exists else "Unavailable / archived",
                    f"{len(asset.owners)} song(s)",
                )
            ):
                self.asset_table.setItem(row, column, QTableWidgetItem(value))
        ambiguous = (
            [
                f"Ambiguous field remains read-only: {p}"
                for p, count in Counter(p for p, _ in song.fields).items()
                if count > 1
            ]
            if song
            else []
        )
        self.problems.setPlainText("\n".join((*problems, *ambiguous)) or "No reported problems.")

    def selected_asset(self) -> Asset | None:
        row = self.asset_table.currentRow()
        return self.assets[row] if 0 <= row < len(self.assets) else None
