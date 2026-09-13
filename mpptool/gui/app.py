"""Einstiegspunkt der Desktop-Anwendung."""
from __future__ import annotations

import sys


def run(db_path: str | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MPP-Auswertungstool")
    win = MainWindow(db_path=db_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
