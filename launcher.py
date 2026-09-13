"""Einstiegspunkt für die gepackte Anwendung (PyInstaller) – startet die GUI."""
import sys

from mpptool.gui.app import run

if __name__ == "__main__":
    sys.exit(run())
