from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtTest import QAbstractItemModelTester, QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QToolBar
from qfluentwidgets import PrimaryPushButton, Theme

from ksm2sdvx.common.jobs import JobControl
from ksm2sdvx.packs.application import open_pack
from ksm2sdvx.packs.discovery import inspect_game
from ksm2sdvx.packs.draft import set_field
from ksm2sdvx.packs.models import Song
from ksm2sdvx.packs.planning import plan_changes
from ksm2sdvx.ui.dialogs import ReviewDialog
from ksm2sdvx.ui.models import SongRow
from ksm2sdvx.ui.slots import ChartSlotPicker
from ksm2sdvx.ui.window import MainWindow
from tests.packs.helpers import installation


def open_custom(window: MainWindow, root: Path) -> None:
    workspace = inspect_game(installation(root))
    window.workspace_opened(workspace)
    window.pack_opened(open_pack(workspace, workspace.pack("custom")))


def choose_message(text: str) -> None:
    def click() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, QMessageBox)
        button = next(b for b in modal.buttons() if b.text().replace("&", "") == text)
        button.click()

    QTimer.singleShot(10, click)


def test_startup_always_requires_selection(window: MainWindow) -> None:
    assert window.stack.currentIndex() == 0
    assert window.workspace is None
    assert window.select_action.isEnabled() and not window.new_action.isEnabled()
    assert window.select_action.shortcut().toString() == "Ctrl+O"
    assert window.review_action.shortcut().toString() == "Ctrl+S"


def test_table_edit_and_delete_keyboard(
    window: MainWindow, tmp_path: Path, app: QApplication
) -> None:
    open_custom(window, tmp_path / "game")
    title = window.inspector.findChild(QLineEdit, "info/title_name")
    assert title is not None
    title.setFocus()
    title.selectAll()
    QTest.keyClicks(title, "Edited")
    QTest.keyClick(title, Qt.Key.Key_Tab)
    app.processEvents()
    assert window.draft is not None and window.draft.dirty
    assert window.model.rows[0].song.title == "Edited"
    artist = window.inspector.findChild(QLineEdit, "info/artist_name")
    assert artist is not None and artist.hasFocus()
    artist.selectAll()
    QTest.keyClicks(artist, "New artist")
    QTest.keyClick(artist, Qt.Key.Key_Tab)
    assert window.model.rows[0].song.artist == "New artist"
    window.table.setFocus()
    QTest.keyClick(window.table, Qt.Key.Key_Delete)
    assert window.draft.removed == (0,)
    assert window.model.rows[0].status == "Remove"
    QTest.keyClick(window.table, Qt.Key.Key_Delete)
    assert not window.draft.removed


def test_dirty_navigation_cancel_discard_and_review(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    assert window.draft is not None
    original = window.draft
    window.draft = set_field(original, 0, "info/title_name", "Changed")
    navigated: list[bool] = []
    choose_message("Cancel")
    window.navigate(lambda: navigated.append(True))
    assert not navigated and window.draft.dirty
    choose_message("Discard")
    window.navigate(lambda: navigated.append(True))
    assert navigated and window.draft is not None and not window.draft.dirty
    window.draft = set_field(original, 0, "info/title_name", "Changed")
    choose_message("Review")
    window.navigate(lambda: navigated.append(False))
    assert window.worker is not None

    # Cancel the review when planning completes; no navigation and no live write.
    def cancel_review() -> None:
        modal = QApplication.activeModalWidget()
        if isinstance(modal, ReviewDialog):
            modal.reject()
        else:
            QTimer.singleShot(10, cancel_review)

    QTimer.singleShot(10, cancel_review)
    for _ in range(100):
        QTest.qWait(10)
        if not window.progress.isVisible():
            break
    assert navigated == [True] and window.draft.dirty


def test_review_requires_game_closed(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    assert window.workspace is not None and window.draft is not None
    plan = plan_changes(window.workspace, set_field(window.draft, 0, "info/title_name", "Edit"))
    dialog = ReviewDialog(plan, (), window)
    closed = dialog.findChild(QCheckBox)
    apply = dialog.findChild(PrimaryPushButton, "applyChanges")
    assert apply is not None and closed is not None
    assert not apply.isEnabled()
    closed.setChecked(True)
    assert apply.isEnabled()
    dialog.close()


def test_large_library_filter_sort_and_selection(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    rows = tuple(
        SongRow(
            Song(
                i,
                i + 1,
                (
                    ("info/title_name", f"Song {i:05}"),
                    ("info/artist_name", "Artist"),
                    ("info/bpm_min", "12000"),
                    ("info/bpm_max", "12000"),
                ),
            ),
            "Ready",
        )
        for i in range(12000)
    )
    window.model.set_rows(rows)
    tester = QAbstractItemModelTester(
        window.model, QAbstractItemModelTester.FailureReportingMode.Fatal
    )
    window.search.setText("Song 11999")
    assert window.proxy.rowCount() == 1
    window.table.setCurrentIndex(window.proxy.index(0, 0))
    assert window.selected_index() == 11999
    window.search.clear()
    window.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert window.proxy.index(0, 0).data() == "12000"
    assert tester.model() is window.model


def test_background_job_stays_responsive_and_completes_on_gui_thread(
    window: MainWindow, app: QApplication
) -> None:
    ready = Event()
    completions: list[object] = []

    def operation(control: JobControl) -> str:
        control.checkpoint("Preparing")
        ready.wait(2)
        return "done"

    def done(value: object) -> None:
        assert QThread.currentThread() == app.thread()
        completions.append(value)

    window.start(operation, done)
    QTimer.singleShot(20, ready.set)
    for _ in range(100):
        QTest.qWait(10)
        if completions:
            break
    assert completions == ["done"]
    assert window.worker is None


def test_original_editor_readonly(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    assert window.workspace is not None
    original = window.workspace.packs[0]
    window.pack_opened(open_pack(window.workspace, original))
    title = window.inspector.findChild(QLineEdit, "info/title_name")
    assert title is not None and title.isReadOnly()
    assert not window.remove_song_action.isEnabled()


def test_new_pack_discard_resets_tree(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    assert window.draft is not None
    window.draft = replace(window.draft, create=True)
    choose_message("Discard")
    window.navigate(lambda: None)
    assert window.draft is None and not window.model.rows


def test_fluent_menu_keyboard_and_shared_actions(
    window: MainWindow, tmp_path: Path, app: QApplication
) -> None:
    open_custom(window, tmp_path / "game")
    assert not window.findChildren(QToolBar)
    assert window.review_action in window.menus.menus[1].actions()
    window.menus.buttons[1].setFocus()
    QTest.keyClick(window.menus.buttons[1], Qt.Key.Key_Space)
    app.processEvents()
    edit = window.menus.menus[1]
    assert edit.isVisible()
    # The first enabled entry is Find song; Enter must invoke its shared QAction.
    QTest.keyClick(edit.view, Qt.Key.Key_Return)
    assert not edit.isVisible()
    assert window.search.hasFocus()
    window.menus.open_menu(0)
    QTest.keyClick(window.menus.menus[0].view, Qt.Key.Key_Right)
    assert window.menus.menus[1].isVisible()
    QTest.keyClick(window.menus.menus[1].view, Qt.Key.Key_Escape)
    assert not any(menu.isVisible() for menu in window.menus.menus)


def test_footer_counts_filter_and_pending_edits(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    assert window.footer.counts.text() == "1 song  ·  1 selected"
    title = window.inspector.findChild(QLineEdit, "info/title_name")
    assert title is not None
    title.setFocus()
    title.selectAll()
    QTest.keyClicks(title, "New title")
    QTest.keyClick(title, Qt.Key.Key_Tab)
    assert window.footer.message.text().startswith("1 pending change")
    assert window.inspector.title_label is not None
    assert window.inspector.title_label.text() == "New title"
    window.search.setText("No matching song")
    assert window.footer.counts.text() == "0 of 1 song"


def test_inspector_tabs_and_slot_keyboard(window: MainWindow, tmp_path: Path) -> None:
    open_custom(window, tmp_path / "game")
    window.inspector.tabs.setCurrentItem("Charts")
    assert window.inspector.pages.currentWidget() is window.inspector.charts
    picker = window.inspector.findChild(ChartSlotPicker)
    assert picker is not None
    picker.setFocus()
    QTest.keyClick(picker, Qt.Key.Key_Down)
    assert picker.currentText() == "advanced"
    QTest.keyClick(picker, Qt.Key.Key_Home)
    assert picker.currentText() == "novice"
    window.inspector.tabs.setCurrentItem("Problems")
    assert window.inspector.pages.currentWidget() is window.inspector.problems


def test_theme_survives_restart_without_reopening_workspace(
    window: MainWindow, tmp_path: Path
) -> None:
    open_custom(window, tmp_path / "game")
    window.choose_theme(Theme.DARK)
    window.save_layout()
    reopened = MainWindow(window.settings)
    try:
        assert reopened.theme is Theme.DARK
        assert reopened.theme_actions[Theme.DARK].isChecked()
        assert reopened.stack.currentIndex() == 0 and reopened.workspace is None
    finally:
        reopened.close()
        window.choose_theme(Theme.AUTO)
