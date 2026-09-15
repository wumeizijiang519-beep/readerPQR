"""Visible application notices and a local copy of the distribution license."""
from pathlib import Path
import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
from PySide6.QtCore import Qt


def install_notices(window):
    action = QAction("关于 readerPQR / 开源许可", window)
    window.menuBar().addMenu("帮助").addAction(action)

    def show():
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        dialog = QDialog(window)
        dialog.setWindowTitle("readerPQR 0.1.0 · 开源许可")
        dialog.resize(750, 570)
        layout = QVBoxLayout(dialog)
        notice = QLabel("readerPQR · Copyright (C) 2026 readerPQR contributors\nAGPL-3.0-only · 本软件不提供任何担保。你可以依照该许可复制、修改和再分发。\n源码：https://github.com/wumeizijiang519-beep/readerPQR\n第三方组件保留各自的版权及许可，详见发行目录中的 THIRD_PARTY_NOTICES.md。")
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(notice)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        try:
            text.setPlainText((root / "LICENSE").read_text(encoding="utf-8"))
        except OSError:
            text.setPlainText("完整许可见项目根目录 LICENSE，或 https://www.gnu.org/licenses/agpl-3.0.txt")
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    action.triggered.connect(show)
