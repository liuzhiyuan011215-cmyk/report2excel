"""桌面程序入口：report2excel-gui 或 python -m report2excel.gui"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import ASSETS_DIR, install_theme


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Report2Excel")
    app.setApplicationDisplayName("Report2Excel")
    install_theme(app)
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def main() -> int:
    app = create_app()
    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
