"""Optional Qt application entry point. Core imports never load Qt."""


def main() -> int:
    import sys

    try:
        from PySide6.QtWidgets import QApplication

        from ksm2sdvx.ui.window import MainWindow
    except ModuleNotFoundError as exc:
        raise SystemExit("Install the UI extra: uv run --extra ui ksm2sdvx-gui") from exc

    app = QApplication(sys.argv)
    app.setOrganizationName("ksm2sdvx")
    app.setApplicationName("Song Pack Manager")
    window = MainWindow()
    window.show()
    return app.exec()
