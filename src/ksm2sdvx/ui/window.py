"""Native desktop shell and orchestration of immutable application results."""

import tempfile
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QByteArray,
    QModelIndex,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Slot,
)
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    PrimaryPushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    TableView,
    Theme,
    TitleLabel,
    TreeWidget,
)

from ksm2sdvx.common.errors import Ksm2SdvxError
from ksm2sdvx.common.jobs import JobControl, Progress
from ksm2sdvx.music.models import S3vMusicSettings
from ksm2sdvx.packs.application import (
    OpenedPack,
    ToolPaths,
    add_prepared,
    export_pack,
    open_pack,
    open_workspace,
    prepare_asset,
    prepare_generated,
    prepare_kson,
    prepared_assets,
    remove_song,
)
from ksm2sdvx.packs.discovery import inspect_game, pack_root
from ksm2sdvx.packs.draft import create_draft, next_song_id, set_field
from ksm2sdvx.packs.models import (
    ORIGINAL,
    Asset,
    ChangePlan,
    PackDraft,
    PreparedSong,
    Recovery,
    Replacement,
    Workspace,
)
from ksm2sdvx.packs.paths import contained
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.packs.storage import apply_changes, list_recovery, recover_pending, restore_last
from ksm2sdvx.ui.chrome import MenuBar, WorkspaceFooter
from ksm2sdvx.ui.dialogs import KsonDialog, RecoveryDialog, ReviewDialog, ToolsDialog
from ksm2sdvx.ui.inspector import Inspector
from ksm2sdvx.ui.jobs import Outcome, Worker
from ksm2sdvx.ui.models import SongTableModel, song_rows
from ksm2sdvx.ui.theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else QSettings()
        self.workspace: Workspace | None = None
        self.draft: PackDraft | None = None
        self.assets: tuple[Asset, ...] = ()
        self.worker: Worker | None = None
        self._completed: Callable[[object], None] = lambda _: None
        self._after_apply: Callable[[], object] | None = None
        self._area = tempfile.TemporaryDirectory(prefix="ksm2sdvx-draft-")
        self.area = Path(self._area.name)
        self.tools = ToolPaths(
            self.setting_text("tools/ffmpeg", "ffmpeg"),
            self.setting_text("tools/ffprobe", "ffprobe"),
        )
        self._thumbnails: list[Worker] = []
        self._selection_generation = 0
        self._actions: list[QAction] = []
        self.theme = Theme.__members__.get(
            self.setting_text("appearance/theme", "AUTO"), Theme.AUTO
        )
        apply_theme(self, self.theme)
        self.resize(1440, 880)
        self.setMinimumSize(1120, 680)
        self._build_shell()
        self.update_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self._restore_layout()
        self.refresh_state()

    def setting_text(self, key: str, default: str = "") -> str:
        value: object = self.settings.value(key, default)
        return value if isinstance(value, str) else default

    def action(self, text: str, callback: Callable[[], object], shortcut: str = "") -> QAction:
        action = QAction(text.replace("&", ""), self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        self._actions.append(action)
        self.addAction(action)
        return action

    def _build_shell(self) -> None:
        self.select_action = self.action("Select &game folder…", self.select_game, "Ctrl+O")
        self.new_action = self.action("&New song pack…", self.new_pack, "Ctrl+N")
        self.review_action = self.action("&Review changes…", self.review, "Ctrl+S")
        self.discard_action = self.action("&Discard changes", self.discard)
        self.remove_pack_action = self.action("Remove song &pack", self.remove_pack)
        self.remove_song_action = self.action(
            "Stage song removal / undo removal", self.remove_selected, "Delete"
        )
        self.removeAction(self.remove_song_action)
        self.remove_song_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.import_action = self.action("Import &KSON song…", self.import_kson)
        self.generated_action = self.action("Import &generated song pack…", self.import_generated)
        self.replace_action = self.action("Replace selected &asset…", self.replace_asset)
        self.export_action = self.action("&Export song pack…", self.export)
        self.recovery_action = self.action("Workspace &Recovery…", self.recovery)
        self.refresh_action = self.action("Re&fresh workspace", self.refresh, "F5")
        self.tools_action = self.action("&Tool locations…", self.configure_tools)
        self.search_action = self.action("&Find song", self.focus_search, "Ctrl+F")
        self.exit_action = self.action("E&xit", self.close, "Alt+F4")
        self.menus = MenuBar(self)
        self.setMenuWidget(self.menus)
        file_menu = self.menus.add_menu("File", "F")
        file_menu.addActions([self.select_action, self.new_action, self.export_action])
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        edit_menu = self.menus.add_menu("Edit", "E")
        edit_menu.addActions(
            [
                self.search_action,
                self.review_action,
                self.discard_action,
                self.remove_song_action,
                self.remove_pack_action,
            ]
        )
        pack_menu = self.menus.add_menu("Song pack", "S")
        pack_menu.addActions([self.import_action, self.generated_action, self.replace_action])
        workspace_menu = self.menus.add_menu("Workspace", "W")
        workspace_menu.addActions([self.refresh_action, self.recovery_action, self.tools_action])
        appearance = self.menus.add_menu("Appearance", "A", checkable=True)
        themes = QActionGroup(self)
        self.theme_actions: dict[Theme, QAction] = {}
        for label, theme in (
            ("Follow system", Theme.AUTO),
            ("Light", Theme.LIGHT),
            ("Dark", Theme.DARK),
        ):
            action = self.action(label, partial(self.choose_theme, theme))
            action.setCheckable(True)
            themes.addAction(action)
            appearance.addAction(action)
            self.theme_actions[theme] = action
        self.action_icons = (
            (self.select_action, FluentIcon.FOLDER),
            (self.new_action, FluentIcon.ADD),
            (self.import_action, FluentIcon.MUSIC),
            (self.generated_action, FluentIcon.FOLDER_ADD),
            (self.review_action, FluentIcon.SAVE),
            (self.recovery_action, FluentIcon.HISTORY),
            (self.remove_song_action, FluentIcon.DELETE),
            (self.remove_pack_action, FluentIcon.DELETE),
            (self.export_action, FluentIcon.DOWNLOAD),
            (self.refresh_action, FluentIcon.SYNC),
            (self.tools_action, FluentIcon.SETTING),
            (self.search_action, FluentIcon.SEARCH),
            (self.replace_action, FluentIcon.EDIT),
        )
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setSpacing(16)
        welcome_layout.addStretch(2)
        self.welcome_icon = QLabel()
        self.welcome_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(self.welcome_icon)
        eyebrow = CaptionLabel("SONG PACK MANAGER")
        eyebrow.setObjectName("secondary")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(eyebrow)
        title = TitleLabel("Select the game folder")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(title)
        note = BodyLabel("Open your library to create and edit song packs.")
        note.setObjectName("secondary")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        button = PrimaryPushButton("Select the game folder…")
        button.setMinimumWidth(220)
        button.clicked.connect(self.select_action.trigger)
        row.addWidget(button)
        row.addStretch()
        welcome_layout.addLayout(row)
        hint = CaptionLabel("Choose the folder containing data/others/music_db.xml.")
        hint.setObjectName("secondary")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(hint)
        welcome_layout.addSpacing(24)
        steps = CaptionLabel(
            "Select folder   →   Choose a song pack   →   Edit   →   Review & apply"
        )
        steps.setObjectName("secondary")
        steps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(steps)
        welcome_layout.addStretch(3)
        self.stack.addWidget(welcome)
        workspace_page = QWidget()
        workspace_layout = QVBoxLayout(workspace_page)
        workspace_layout.setContentsMargins(12, 8, 12, 12)
        workspace_layout.setSpacing(16)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(12)
        sidebar = QWidget()
        sidebar.setMinimumWidth(180)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 8, 4, 0)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(StrongBodyLabel("Song packs"))
        self.tree = TreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumWidth(170)
        self.tree.currentItemChanged.connect(self.pack_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.tree.addActions([self.new_action, self.remove_pack_action, self.export_action])
        sidebar_layout.addWidget(self.tree)
        self.splitter.addWidget(sidebar)
        center = QWidget()
        center.setObjectName("libraryPanel")
        center.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(20, 20, 20, 12)
        center_layout.setSpacing(12)
        self.pack_heading = SubtitleLabel("Choose a song pack")
        center_layout.addWidget(self.pack_heading)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Search title, artist or ID (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        center_layout.addWidget(self.search)
        self.model = SongTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = TableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setBorderVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((85, 190, 140, 95, 130, 100)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().currentRowChanged.connect(self.song_selected)
        self.table.addActions([self.remove_song_action, self.review_action])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        center_layout.addWidget(self.table)
        self.splitter.addWidget(center)
        self.inspector = Inspector()
        self.inspector.setMinimumWidth(360)
        self.inspector.edited.connect(self.edit_field)
        self.inspector.asset_table.addAction(self.replace_action)
        self.inspector.asset_table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.splitter.addWidget(self.inspector)
        self.splitter.setSizes([210, 790, 400])
        self.splitter.setCollapsible(1, False)
        workspace_layout.addWidget(self.splitter, 1)
        self.stack.addWidget(workspace_page)
        self.footer = WorkspaceFooter()
        root_layout.addWidget(self.footer)
        self.progress = self.footer.progress
        self.cancel = self.footer.cancel
        self.cancel.clicked.connect(self.cancel_job)
        self.search.textChanged.connect(self.update_counts)
        self.table.selectionModel().currentRowChanged.connect(self.update_counts)

    def update_counts(self) -> None:
        total, shown = len(self.model.rows), self.proxy.rowCount()
        if self.draft is None:
            self.footer.counts.clear()
            return
        noun = "song" if total == 1 else "songs"
        count = f"{shown} of {total} {noun}" if shown != total else f"{total} {noun}"
        selection = "  ·  1 selected" if self.selected_index() is not None else ""
        self.footer.counts.setText(count + selection)

    def choose_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.settings.setValue("appearance/theme", theme.name)
        self.update_theme()

    def system_theme_changed(self) -> None:
        if self.theme is Theme.AUTO:
            self.update_theme()

    def update_theme(self) -> None:
        apply_theme(self, self.theme)
        for theme, action in self.theme_actions.items():
            action.setChecked(theme is self.theme)
        for action, icon in self.action_icons:
            action.setIcon(icon.icon())
        self.setWindowIcon(FluentIcon.MUSIC_FOLDER.icon())
        self.welcome_icon.setPixmap(FluentIcon.MUSIC_FOLDER.icon().pixmap(64, 64))
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None:
                original = item.data(0, Qt.ItemDataRole.UserRole) == ORIGINAL
                item.setIcon(
                    0, (FluentIcon.LIBRARY if original else FluentIcon.MUSIC_FOLDER).icon()
                )

    def _restore_layout(self) -> None:
        for key, restore in (
            ("window/geometry", self.restoreGeometry),
            ("window/splitter", self.splitter.restoreState),
            ("window/columns", self.table.horizontalHeader().restoreState),
        ):
            value: object = self.settings.value(key)
            if isinstance(value, QByteArray):
                restore(value)
        # Fluent delegates reserve more horizontal padding than the platform delegate.
        self.table.setColumnWidth(0, max(85, self.table.columnWidth(0)))

    def save_layout(self) -> None:
        for key, value in (
            ("window/geometry", self.saveGeometry()),
            ("window/splitter", self.splitter.saveState()),
            ("window/columns", self.table.horizontalHeader().saveState()),
        ):
            self.settings.setValue(key, value)

    def refresh_state(self) -> None:
        busy = self.worker is not None
        editable = (
            self.draft is not None
            and not self.draft.pack.readonly
            and self.draft.pack.database is not None
        )
        dirty = self.draft is not None and self.draft.dirty
        for action in self._actions:
            action.setEnabled(not busy)
        for action in (
            self.new_action,
            self.refresh_action,
            self.recovery_action,
            self.search_action,
        ):
            action.setEnabled(not busy and self.workspace is not None)
        for action in (
            self.import_action,
            self.generated_action,
            self.replace_action,
            self.remove_song_action,
            self.remove_pack_action,
            self.export_action,
        ):
            action.setEnabled(not busy and editable and not (self.draft and self.draft.remove_pack))
        self.review_action.setEnabled(not busy and dirty)
        self.discard_action.setEnabled(not busy and dirty)
        self.stack.setEnabled(not busy)
        name = self.draft.pack.name if self.draft else "Select the game folder"
        self.setWindowTitle(f"{name}[*] — Song Pack Manager")
        self.setWindowModified(dirty)
        self.pack_heading.setText(
            "Original library" if name == ORIGINAL else name if self.draft else "Choose a song pack"
        )
        self.update_counts()
        if not busy:
            if self.draft is not None and dirty:
                count = (
                    len(self.draft.edits)
                    + len(self.draft.additions)
                    + len(self.draft.removed)
                    + len(self.draft.replacements)
                    + int(self.draft.create)
                    + int(self.draft.remove_pack)
                )
                self.footer.set_message(
                    f"{count} pending change{'s' if count != 1 else ''}  ·  Review with Ctrl+S"
                )
            else:
                self.footer.set_message("Ready" if self.workspace else "No game folder selected")

    def error(self, message: str) -> None:
        QMessageBox.warning(self, "Song Pack Manager", message)

    def start(
        self, operation: Callable[[JobControl], object], completed: Callable[[object], None]
    ) -> None:
        if self.worker is not None:
            return
        self._completed = completed
        self.worker = Worker(operation, self)
        self.worker.result.connect(self.job_finished, Qt.ConnectionType.QueuedConnection)
        self.worker.progress.connect(self.job_progress, Qt.ConnectionType.QueuedConnection)
        self.progress.report()
        self.cancel.setEnabled(True)
        self.cancel.show()
        self.refresh_state()
        self.worker.start()

    @Slot(object)
    def job_progress(self, value: object) -> None:
        if isinstance(value, Progress):
            self.footer.set_message(value.stage)
            self.progress.report(value.completed, value.total)
            if value.stage.startswith("Committing"):
                self.cancel.setEnabled(False)

    @Slot(object)
    def job_finished(self, value: object) -> None:
        assert isinstance(value, Outcome)
        if self.worker is not None:
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
        self.progress.finish()
        self.cancel.hide()
        self.refresh_state()
        if value.error:
            self._after_apply = None
            if value.cancelled:
                self.footer.set_message(value.error)
            else:
                self.error(value.error)
        else:
            try:
                self._completed(value.value)
            except (Ksm2SdvxError, OSError, ValueError) as exc:
                self.error(str(exc))

    def cancel_job(self) -> None:
        if self.worker is not None:
            self.worker.cancelled.set()
            self.cancel.setEnabled(False)
            self.footer.set_message(
                "Cancellation requested; the current media operation must finish."
            )

    def navigate(self, proceed: Callable[[], object]) -> None:
        if self.worker is not None:
            return
        if self.draft is None or not self.draft.dirty:
            proceed()
            return
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Pending changes",
            "Review or discard the current song pack draft before continuing.",
            parent=self,
        )
        review = box.addButton("Review", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() == review:
            self._after_apply = proceed
            self.review()
        elif box.clickedButton() == discard:
            self._discard_local()
            proceed()

    def select_game(self) -> None:
        self.navigate(self._choose_game)

    def _choose_game(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, "Select the game folder", self.setting_text("workspace/last")
        )
        if name:
            self.settings.setValue("workspace/last", name)
            self.start(lambda control: open_workspace(Path(name), control), self.workspace_opened)

    def workspace_opened(self, value: object) -> None:
        assert isinstance(value, Workspace)
        self.workspace = value
        self._selection_generation += 1
        self.draft = None
        self.model.set_rows(())
        self.inspector.show_song(None, True, (), ())
        self.tree.blockSignals(True)
        self.tree.clear()
        for pack in value.packs:
            label = (
                "Original library"
                if pack.name == ORIGINAL
                else pack.name + (" (read-only)" if pack.readonly else "")
            )
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, pack.name)
            item.setIcon(
                0, (FluentIcon.LIBRARY if pack.name == ORIGINAL else FluentIcon.MUSIC_FOLDER).icon()
            )
            item.setToolTip(0, label + (" — Read-only" if pack.readonly else ""))
            self.tree.addTopLevelItem(item)
        self.stack.setCurrentIndex(1)
        self.tree.setCurrentIndex(QModelIndex())
        self.tree.blockSignals(False)
        self.refresh_state()
        if value.recovery_error:
            self.footer.set_message(
                f"Recovery required; workspace is read-only: {value.recovery_error}"
            )

    def _select_tree_name(self, name: str) -> None:
        self.tree.blockSignals(True)
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            assert item is not None
            if item.data(0, Qt.ItemDataRole.UserRole) == name:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def pack_selected(
        self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None
    ) -> None:
        del previous
        if current is None or self.workspace is None:
            return
        name: object = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(name, str) or (self.draft and self.draft.pack.name == name):
            return
        if self.draft is not None:
            self._select_tree_name(self.draft.pack.name)
        self.navigate(lambda: self.load_pack(name))

    def load_pack(self, name: str) -> None:
        assert self.workspace is not None
        workspace = self.workspace
        pack = workspace.pack(name)
        self.start(lambda control: open_pack(workspace, pack, control), self.pack_opened)

    def pack_opened(self, value: object) -> None:
        assert isinstance(value, OpenedPack)
        self.draft = PackDraft(value.pack)
        self.assets = value.assets
        self._select_tree_name(value.pack.name)
        self.search.clear()
        self.refresh_rows()

    def refresh_rows(self, selected: int | None = None, *, refresh_details: bool = True) -> None:
        if self.workspace is None or self.draft is None:
            return
        changed = {r.relative for r in self.draft.replacements}
        indices = frozenset(
            index for asset in self.assets if asset.relative in changed for index in asset.owners
        )
        blocked = self.table.selectionModel().blockSignals(not refresh_details)
        self.model.set_rows(song_rows(self.workspace, self.draft, indices))
        for index, row in enumerate(self.model.rows):
            if row.song.index == selected:
                self.table.setCurrentIndex(self.proxy.mapFromSource(self.model.index(index, 0)))
                break
        else:
            if self.proxy.rowCount():
                self.table.setCurrentIndex(self.proxy.index(0, 0))
            else:
                self.inspector.show_song(
                    None, True, (), tuple(d.message for d in self.draft.pack.diagnostics)
                )
        self.table.selectionModel().blockSignals(blocked)
        if not refresh_details and self.selected_index() != selected:
            self.song_selected(self.table.currentIndex(), QModelIndex())
        elif not refresh_details:
            source = self.proxy.mapToSource(self.table.currentIndex())
            if source.isValid():
                self.inspector.update_summary(self.model.rows[source.row()].song)
        self.refresh_state()

    def selected_index(self) -> int | None:
        source = self.proxy.mapToSource(self.table.currentIndex())
        return self.model.rows[source.row()].song.index if source.isValid() else None

    def song_selected(self, current: QModelIndex, previous: QModelIndex) -> None:
        del previous
        self._selection_generation += 1
        if self.draft is None or self.workspace is None:
            return
        source = self.proxy.mapToSource(current)
        if not source.isValid():
            self.inspector.show_song(None, True, (), ())
            return
        row = self.model.rows[source.row()]
        song = row.song
        assets = tuple(a for a in self.assets if song.index in a.owners)
        prepared: PreparedSong | None = None
        problems = [d.message for d in self.draft.pack.diagnostics]
        if row.status == "Conflict":
            problems.append("Duplicate song ID: changes affecting this identity are blocked.")
        if not self.workspace.complete:
            problems.append("Installation ID inventory is incomplete; new songs cannot be added.")
        if self.draft.pack.database and song.index >= len(self.draft.pack.database.songs):
            prepared = self.draft.additions[song.index - len(self.draft.pack.database.songs)]
            assets = prepared_assets(prepared, song.index)
            problems.extend(d.message for d in prepared.diagnostics)
        self.inspector.show_song(
            song,
            self.draft.pack.readonly or self.draft.remove_pack or song.index in self.draft.removed,
            assets,
            tuple(problems),
        )
        generation = self._selection_generation
        jacket = next(
            (
                a
                for a in assets
                if a.kind == "Jacket" and a.exists and a.relative.endswith("_s.png")
            ),
            None,
        )
        if jacket is not None:
            root = pack_root(self.workspace, self.draft.pack)
            relative = jacket.relative
            prepared_path = (
                next((a.source for a in prepared.assets if a.relative == relative), None)
                if prepared
                else None
            )
            replacement_path = next(
                (a.source for a in self.draft.replacements if a.relative == relative), None
            )

            def read(control: JobControl) -> tuple[int, bytes]:
                control.checkpoint("Loading jacket")
                path = replacement_path or prepared_path or contained(root, relative)
                return generation, path.read_bytes() if path.stat().st_size < 8_000_000 else b""

            worker = Worker(read, self)
            worker.result.connect(self.thumbnail_ready, Qt.ConnectionType.QueuedConnection)
            self._thumbnails.append(worker)
            worker.start()

    @Slot(object)
    def thumbnail_ready(self, result: object) -> None:
        from PySide6.QtGui import QPixmap

        value: object = result.value if isinstance(result, Outcome) else None
        if isinstance(value, tuple):
            generation, content = cast(tuple[object, object], value)
            if generation == self._selection_generation and isinstance(content, bytes):
                pixmap = QPixmap()
                if pixmap.loadFromData(content):
                    self.inspector.preview.setPixmap(
                        pixmap.scaled(
                            self.inspector.preview.width(),
                            self.inspector.preview.height(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
        for worker in tuple(self._thumbnails):
            if worker.isFinished():
                self._thumbnails.remove(worker)
                worker.deleteLater()

    @Slot(int, str, str)
    def edit_field(self, index: int, path: str, value: str) -> None:
        if self.draft is None:
            return
        try:
            self.draft = set_field(self.draft, index, path, value)
        except Ksm2SdvxError as exc:
            self.error(str(exc))
            self.refresh_rows(index)
            return
        self.refresh_rows(index, refresh_details=False)

    def new_pack(self) -> None:
        self.navigate(self._new_pack)

    def _new_pack(self) -> None:
        if self.workspace is None:
            return
        name, accepted = QInputDialog.getText(self, "New song pack", "Folder name")
        if accepted:
            try:
                self.draft = create_draft(self.workspace, name)
            except Ksm2SdvxError as exc:
                self.error(str(exc))
                return
            self.assets = ()
            item = QTreeWidgetItem([f"{name} (new)"])
            item.setIcon(0, FluentIcon.MUSIC_FOLDER.icon())
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            self.tree.addTopLevelItem(item)
            self._select_tree_name(name)
            self.refresh_rows()

    def remove_selected(self) -> None:
        if self.draft is not None and (index := self.selected_index()) is not None:
            try:
                self.draft = remove_song(self.draft, index)
                self.refresh_rows(index)
            except Ksm2SdvxError as exc:
                self.error(str(exc))

    def remove_pack(self) -> None:
        if self.draft is None:
            return
        if self.draft.create:
            self.discard()
        else:
            self.draft = replace(self.draft, remove_pack=True)
            self.refresh_rows(self.selected_index())
            self.footer.set_message(
                "Pack removal staged. Review to apply or discard to keep the pack."
            )

    def discard(self) -> None:
        if self.workspace is None or self.draft is None:
            return
        name, created = self.draft.pack.name, self.draft.create
        self.draft = None
        self.workspace_opened(self.workspace)
        if not created:
            self.load_pack(name)

    def _discard_local(self) -> None:
        if self.draft is not None and not self.draft.create:
            self.draft = PackDraft(self.draft.pack)
            self.refresh_rows()
        elif self.workspace is not None:
            self.workspace_opened(self.workspace)

    def review(self) -> None:
        focused = cast(QWidget | None, self.focusWidget())
        if focused is not None:
            focused.clearFocus()
        if self.workspace is None or self.draft is None:
            return
        workspace, draft = self.workspace, self.draft

        def plan(control: JobControl) -> ChangePlan:
            control.checkpoint("Validating and planning changes")
            result = plan_changes(workspace, draft)
            control.checkpoint("Review ready")
            return result

        self.start(plan, self.review_ready)

    def review_ready(self, value: object) -> None:
        assert isinstance(value, ChangePlan)
        warnings = (
            tuple(d.message for a in self.draft.additions for d in a.diagnostics)
            if self.draft
            else ()
        )
        dialog = ReviewDialog(value, warnings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:

            def apply(control: JobControl) -> Workspace:
                apply_changes(value, control=control)
                return inspect_game(value.workspace.root)

            self.start(apply, self.applied)
        else:
            self._after_apply = None

    def applied(self, value: object) -> None:
        assert isinstance(value, Workspace)
        name = self.draft.pack.name if self.draft else ""
        after = self._after_apply
        self._after_apply = None
        self.workspace_opened(value)
        if after is not None:
            after()
        elif any(pack.name == name for pack in value.packs):
            self.load_pack(name)

    def import_kson(self) -> None:
        if self.workspace is None or self.draft is None:
            return
        try:
            song_id = next_song_id(self.workspace, self.draft)
        except Ksm2SdvxError as exc:
            self.error(str(exc))
            return
        dialog = KsonDialog(song_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.config is not None:
            config = dialog.config
            self.start(
                lambda control: prepare_kson(config, self.area, self.tools, control),
                self.song_prepared,
            )

    def import_generated(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Select a generated single-song pack")
        if name:
            self.start(
                lambda control: prepare_generated(Path(name), self.area, control=control),
                self.song_prepared,
            )

    def song_prepared(self, value: object) -> None:
        assert isinstance(value, PreparedSong)
        if self.workspace is not None and self.draft is not None:
            self.draft = add_prepared(self.workspace, self.draft, value)
            assert self.draft.pack.database is not None
            self.refresh_rows(len(self.draft.pack.database.songs) + len(self.draft.additions) - 1)

    def replace_asset(self) -> None:
        asset = self.inspector.selected_asset()
        if asset is None:
            self.error("Select an audio or jacket file in the Assets tab.")
            return
        if len(asset.owners) > 1:
            answer = QMessageBox.question(
                self,
                "Shared asset",
                f"This file is used by {len(asset.owners)} songs. Stage a replacement for all of them?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        source, _ = QFileDialog.getOpenFileName(self, "Choose replacement media")
        if not source:
            return
        audio = S3vMusicSettings()
        if asset.kind == "Preview audio":
            start, accepted = QInputDialog.getInt(
                self, "Preview interval", "Start (milliseconds)", 0, 0, 2**31 - 1
            )
            if not accepted:
                return
            duration, accepted = QInputDialog.getInt(
                self, "Preview interval", "Duration (milliseconds)", 15000, 1, 2**31 - 1
            )
            if not accepted:
                return
            audio = replace(audio, preview_start_ms=start, preview_duration_ms=duration)
        self.start(
            lambda control: prepare_asset(
                asset, Path(source), self.area, tools=self.tools, audio=audio, control=control
            ),
            self.asset_prepared,
        )

    def asset_prepared(self, value: object) -> None:
        assert isinstance(value, Replacement)
        if self.draft is not None:
            selected = self.selected_index()
            count = len(self.draft.pack.database.songs) if self.draft.pack.database else 0
            if selected is not None and selected >= count:
                position = selected - count
                additions = list(self.draft.additions)
                addition = additions[position]
                additions[position] = replace(
                    addition,
                    assets=tuple(
                        value if a.relative == value.relative else a for a in addition.assets
                    ),
                )
                self.draft = replace(self.draft, additions=tuple(additions))
                self.refresh_rows(selected)
                return
            replacements = tuple(a for a in self.draft.replacements if a.relative != value.relative)
            self.draft = replace(self.draft, replacements=(*replacements, value))
            self.refresh_rows(selected)
            self.footer.set_message(f"Replacement staged: {value.relative}")

    def export(self) -> None:
        if self.draft is not None:
            name = self.draft.pack.name
            self.navigate(lambda: self._export(name))

    def _export(self, name: str) -> None:
        if self.workspace is None:
            return
        if not any(pack.name == name for pack in self.workspace.packs):
            return
        pack = self.workspace.pack(name)
        parent = QFileDialog.getExistingDirectory(self, "Select export parent folder")
        if parent:
            folder, accepted = QInputDialog.getText(
                self, "Export song pack", "New folder name", text=pack.name
            )
            if accepted:
                from ksm2sdvx.packs.paths import pack_name

                try:
                    pack_name(folder)
                except Ksm2SdvxError as exc:
                    self.error(str(exc))
                    return
                workspace = self.workspace
                self.start(
                    lambda control: export_pack(workspace, pack, Path(parent) / folder, control),
                    lambda result: self.footer.set_message(f"Exported to {result}"),
                )

    def refresh(self) -> None:
        self.navigate(self._refresh)

    def _refresh(self) -> None:
        if self.workspace is not None:
            root = self.workspace.root
            self.start(lambda control: open_workspace(root, control), self.workspace_opened)

    def recovery(self) -> None:
        self.navigate(self._recovery)

    def _recovery(self) -> None:
        if self.workspace is not None:
            root = self.workspace.root
            self.start(lambda _: list_recovery(root), self.recovery_ready)

    def recovery_ready(self, value: object) -> None:
        assert isinstance(value, tuple)
        records = tuple(
            record for record in cast(tuple[object, ...], value) if isinstance(record, Recovery)
        )
        dialog = RecoveryDialog(records, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and self.workspace is not None:
            root, transaction = self.workspace.root, dialog.transaction
            unfinished = any(
                r.transaction == transaction and r.status != "verified" for r in records
            )

            def restore(_: JobControl) -> Workspace:
                if unfinished:
                    recover_pending(root)
                else:
                    restore_last(root, transaction)
                return inspect_game(root)

            self.start(restore, self.workspace_opened)

    def configure_tools(self) -> None:
        dialog = ToolsDialog(self.tools, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.tools = ToolPaths(dialog.ffmpeg.text(), dialog.ffprobe.text())
            self.settings.setValue("tools/ffmpeg", self.tools.ffmpeg)
            self.settings.setValue("tools/ffprobe", self.tools.ffprobe)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            self.footer.set_message(
                "Wait for the current job, or cancel preparation before closing."
            )
            event.ignore()
            return
        if self.draft is not None and self.draft.dirty:
            event.ignore()
            self.navigate(lambda: QTimer.singleShot(0, self.close))
            return
        self.save_layout()
        for worker in self._thumbnails:
            worker.cancelled.set()
            worker.wait()
        self._thumbnails.clear()
        self._area.cleanup()
        event.accept()
