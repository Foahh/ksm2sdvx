import os
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from ksm2sdvx.ui.window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("qfluentwidgets")


@pytest.fixture(scope="session")
def app() -> QApplication:
    from PySide6.QtWidgets import QApplication

    return QApplication([])


@pytest.fixture
def window(app: QApplication, tmp_path: Path) -> Generator[MainWindow]:
    from PySide6.QtCore import QSettings

    from ksm2sdvx.ui.window import MainWindow

    result = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    result.show()
    app.processEvents()
    yield result
    result.draft = None
    if result.worker is not None:
        result.worker.cancelled.set()
        result.worker.wait()
        app.processEvents()
    result.close()
    app.processEvents()
