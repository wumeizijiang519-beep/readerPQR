from __future__ import annotations

import threading
from PySide6.QtCore import QThread, Signal


class Task(QThread):
    result = Signal(object)
    failed = Signal(str, str)
    translated = Signal(str, str, str)
    block_failed = Signal(str, str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.stop = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self))
        except Exception as exc:
            # Domain exceptions carry sanitized messages; generic exceptions do not.
            from .pdf_engine import PDFError
            from .translate import TranslationError
            safe = isinstance(exc, (PDFError, TranslationError, InterruptedError, ValueError))
            self.failed.emit(type(exc).__name__, str(exc) if safe else "操作失败，请检查文件访问权限或重新启动应用。")
