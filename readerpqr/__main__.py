from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="readerPQR AI bilingual PDF reader")
    parser.add_argument("pdf", nargs="?", help="PDF path to open")
    parser.add_argument("--self-test", action="store_true", help="Offline packaged GUI smoke test; exits automatically")
    parser.add_argument("--output", default="smoke", help="Smoke-test report directory")
    args = parser.parse_args()
    if args.self_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        os.environ["READERPQR_DATA_DIR"] = str(output / "isolated-data")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .ui import ReaderWindow
    from .legal import install_notices
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("readerPQR")
    app.setOrganizationName("readerPQR")
    if args.self_test:
        from .smoke import run_smoke
        try:
            window = run_smoke(output)
            install_notices(window)
            window.show()
            def capture():
                app.processEvents()
                if not window.grab().save(str(output / "readerPQR-windows.png")):
                    (output / "smoke-error.txt").write_text("Screenshot capture failed", encoding="utf-8")
                    app.exit(1)
                    return
                (output / "smoke-ok.txt").write_text("PASS: offline PDF rendering, aligned GUI, exports and cache\n", encoding="utf-8")
                window.close()
                app.quit()
            QTimer.singleShot(800, capture)
            return app.exec()
        except Exception:
            import traceback
            (output / "smoke-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            return 1
    window = ReaderWindow()
    install_notices(window)
    window.show()
    if args.pdf:
        QTimer.singleShot(0, lambda: window.open_path(str(Path(args.pdf).resolve())))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
