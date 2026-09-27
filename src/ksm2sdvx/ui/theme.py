"""Fluent controls with a native window frame and a small set of shell surfaces."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget
from qfluentwidgets import Theme, isDarkTheme, setTheme


def apply_theme(window: QWidget, theme: Theme) -> None:
    # QSettings owns persistence; the library must not create its own config file.
    setTheme(theme, save=False)
    dark = isDarkTheme()
    background = "#202020" if dark else "#f3f3f3"
    surface = "#2b2b2b" if dark else "#ffffff"
    text = "#f2f2f2" if dark else "#1b1b1b"
    border = "#3c3c3c" if dark else "#e3e3e3"
    muted = "#bcbcbc" if dark else "#616161"
    hover = "#383838" if dark else "#e9e9e9"
    palette = window.palette()
    for role, color in (
        (QPalette.ColorRole.Window, background),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Base, surface),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.Button, surface),
        (QPalette.ColorRole.ButtonText, text),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    window.setStyleSheet(f"""
        QMainWindow, QDialog {{ background: {background}; color: {text}; }}
        QWidget#libraryPanel, QWidget#inspector {{
            background: {surface}; border: 1px solid {border}; border-radius: 8px;
        }}
        QWidget#inspectorPage, QScrollArea {{ background: transparent; border: none; }}
        QLabel#secondary {{ color: {muted}; }}
        QLabel#jacketPreview {{ background: {background}; border-radius: 6px; color: {muted}; }}
        QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
        QMenu::item:selected {{ background: {hover}; }}
        QWidget#menuStrip {{ background: {background}; }}
        QWidget#workspaceFooter {{ background: {background}; border-top: 1px solid {border}; }}
        QSplitter::handle {{ background: transparent; }}
        QSplitter::handle:hover {{ background: {border}; }}
    """)
