import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from readerpqr.smoke import run_smoke


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
