import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from readerpqr.smoke import run_smoke


def test_qa_worker_results_and_safe_close(tmp_path, monkeypatch):
    import asyncio
    import time
    from readerpqr.qa_dialog import PaperQADialog
    from readerpqr.translate import Cancelled
    monkeypatch.setenv("READERPQR_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = run_smoke(tmp_path)
    history = []
    dialog = PaperQADialog(window.paper, window.settings, history, parent=window)
    async def answer(*args, **kwargs):
        assert args[1].timeout == 300
        return "依据 [第1页]：<script>只应显示为文字</script>"
    monkeypatch.setattr("readerpqr.qa_dialog.ask_paper", answer)
    dialog.question.setPlainText("核心贡献是什么？")
    dialog.submit()
    def wait_done():
        deadline = time.monotonic() + 3
        while dialog.task is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert dialog.task is None
    wait_done()
    assert len(history) == 2 and "<script>" in dialog.transcript.toPlainText()
    assert dialog.send.isEnabled()
    assert not dialog.wait_timer.isActive()
    async def slow(*args, **kwargs):
        stop = args[-1]
        while not stop.is_set():
            await asyncio.sleep(0.01)
        raise Cancelled("stopped")
    monkeypatch.setattr("readerpqr.qa_dialog.ask_paper", slow)
    dialog.question.setPlainText("追问")
    dialog.submit()
    dialog.reject()
    wait_done()
    assert len(history) == 2
    window.qa_history.extend(history)
    from dataclasses import replace
    window.paper_loaded(replace(window.paper, fingerprint="another-paper"))
    assert window.qa_history == []
    window.close()


def test_gui_offline_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("READERPQR_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = run_smoke(tmp_path)
    try:
        app.processEvents()
        assert window.paper.page_count == 2
        assert window.translation_labels
        window.pages.setCurrentRow(1)
        app.processEvents()
        assert window.current_page == 1
        window.find.setText("validates")
        window.search()
        assert window.page_image.active
        assert (tmp_path / "bilingual.html").exists()
    finally:
        window.close()
        app.processEvents()


def test_nonmodal_qa_allows_navigation_and_isolates_paper_switch(tmp_path, monkeypatch):
    import asyncio
    import time
    from dataclasses import replace
    from PySide6.QtCore import Qt
    monkeypatch.setenv("READERPQR_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = run_smoke(tmp_path)
    monkeypatch.setattr(window, "_ready", lambda: True)
    window.open_qa()
    dialog = window.qa_dialog
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert QApplication.activeModalWidget() is None
    window.open_qa()
    assert window.qa_dialog is dialog and len(window.qa_windows) == 1
    async def late_answer(*args, **kwargs):
        while not args[-1].is_set():
            await asyncio.sleep(0.01)
        return "旧论文的延迟回答"
    monkeypatch.setattr("readerpqr.qa_dialog.ask_paper", late_answer)
    dialog.question.setPlainText("问题")
    dialog.submit()
    window.pages.setCurrentRow(1)
    assert window.current_page == 1
    old_history = window.qa_history
    window.paper_loaded(replace(window.paper, fingerprint="different"))
    assert window.qa_dialog is None and window.qa_history is not old_history
    deadline = time.monotonic() + 3
    while window.qa_windows and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not window.qa_windows and window.qa_history == []
    window.close()


def test_main_window_waits_for_qa_worker_before_exit(tmp_path, monkeypatch):
    import asyncio
    import time
    from PySide6.QtWidgets import QMessageBox
    from readerpqr.translate import Cancelled
    monkeypatch.setenv("READERPQR_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = run_smoke(tmp_path)
    monkeypatch.setattr(window, "_ready", lambda: True)
    async def answer(*args, **kwargs):
        while not args[-1].is_set():
            await asyncio.sleep(0.01)
        raise Cancelled("stopped")
    monkeypatch.setattr("readerpqr.qa_dialog.ask_paper", answer)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.open_qa()
    window.qa_dialog.question.setPlainText("问题")
    window.qa_dialog.submit()
    window.close()
    deadline = time.monotonic() + 3
    while (window.isVisible() or window.qa_windows) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not window.isVisible() and not window.qa_windows


def test_stream_partial_is_visible_copyable_and_not_history(tmp_path, monkeypatch):
    import asyncio
    import time
    from readerpqr.qa_dialog import PaperQADialog
    from readerpqr.translate import TranslationError
    monkeypatch.setenv('READERPQR_DATA_DIR', str(tmp_path / 'data'))
    app = QApplication.instance() or QApplication([])
    window = run_smoke(tmp_path)
    history = []
    dialog = PaperQADialog(window.paper, window.settings, history, parent=window)
    async def interrupted(*args, **kwargs):
        assert kwargs['stream'] is True
        kwargs['on_chunk']('<原文>中文片段')
        await asyncio.sleep(0.15)
        raise TranslationError('连接中断；未自动重发。')
    monkeypatch.setattr('readerpqr.qa_dialog.ask_paper', interrupted)
    dialog.question.setPlainText('问题')
    dialog.submit()
    visible_while_running = False
    deadline = time.monotonic() + 3
    while dialog.task is not None and time.monotonic() < deadline:
        app.processEvents()
        if '<原文>中文片段' in dialog.transcript.toPlainText() and dialog.task is not None:
            visible_while_running = True
        time.sleep(0.01)
    assert dialog.task is None and visible_while_running
    assert history == [] and dialog.question.toPlainText() == '问题'
    assert '回答未完成' in dialog.transcript.toPlainText()
    dialog.copy_answer()
    assert QApplication.clipboard().text() == '【回答未完成】\n<原文>中文片段'
    dialog.clear_history()
    assert dialog.partial_answer == '' and dialog.transcript.toPlainText() == ''
    dialog.close()
    window.close()
