"""Build on Windows; never pretend a Linux build is a Windows executable."""
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.platform != "win32":
    raise SystemExit("Windows packaging must run on Windows. Use the GitHub Actions workflow.")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                "--onedir", "--name", "readerPQR", "--collect-data", "pymupdf",
                "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
                "main.py"], cwd=ROOT, check=True)
output = ROOT / "dist" / "readerPQR"
for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
    if (ROOT / name).exists():
        shutil.copy2(ROOT / name, output / name)
shutil.copytree(ROOT / "docs", output / "docs", dirs_exist_ok=True)
licenses = output / "THIRD_PARTY_LICENSES"
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name", "unknown")
    for file in distribution.files or []:
        if any(word in str(file).lower() for word in ("license", "copying")):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = licenses / name / str(file).replace("..", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(output / "dependency-versions.txt").write_text(
    subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True), encoding="utf-8")
print(output / "readerPQR.exe")
