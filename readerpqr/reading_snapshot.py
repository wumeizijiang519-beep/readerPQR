"""Self-contained, credential-free reading snapshots and Windows shortcuts."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from .models import Block, Paper

def snapshot_directory():
    from PySide6.QtCore import QStandardPaths
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    if not documents:
        raise OSError("无法定位文档文件夹。")
    return Path(documents) / "readerPQR" / "reading-snapshots"


def save_snapshot(paper, translations, page=0, directory=None):
    folder = (Path(directory) if directory else snapshot_directory()) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    target = folder / "source.pdf"
    shutil.copy2(paper.path, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != paper.fingerprint:
        raise ValueError("原 PDF 已发生变化，请重新导入后再创建快捷方式。")
    metadata = asdict(paper)
    metadata["path"] = "source.pdf"
    allowed = {b.id for b in paper.blocks}
    payload = {"version": 1, "paper": metadata, "page": page,
               "translations": {k: v for k, v in translations.items() if k in allowed}}
    path = folder / "reading.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_snapshot(path):
    path = Path(path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("不支持的阅读快照版本。")
    metadata = payload["paper"]
    source = path.parent / "source.pdf"
    if hashlib.sha256(source.read_bytes()).hexdigest() != metadata["fingerprint"]:
        raise ValueError("阅读快照中的 PDF 缺失或已被修改。")
    pages = [[Block(**{**b, "bbox": tuple(b["bbox"])}) for b in page] for page in metadata["pages"]]
    paper = Paper(str(source), metadata["fingerprint"], metadata["title"],
                  metadata["page_count"], pages, metadata["image_only_pages"])
    translations = payload["translations"]
    if not isinstance(translations, dict) or not all(isinstance(v, str) for v in translations.values()):
        raise ValueError("阅读快照中的译文格式无效。")
    return paper, translations, max(0, min(int(payload["page"]), paper.page_count - 1))


def create_shortcut(snapshot, title, desktop=None):
    if sys.platform != "win32":
        raise ValueError("桌面快捷方式目前仅支持 Windows。")
    if desktop is None:
        from PySide6.QtCore import QStandardPaths
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    desktop = Path(desktop)
    desktop.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:65] or "文献"
    link = desktop / f"readerPQR - {name} - {Path(snapshot).parent.name[:8]}.lnk"
    root = Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        executable = sys.executable
        arguments = ["--reading-snapshot", str(snapshot)]
    else:
        executable = str(Path(sys.executable).with_name("pythonw.exe"))
        arguments = [str(root / "main.py"), "--reading-snapshot", str(snapshot)]
    config = {"link": str(link), "target": executable,
              "arguments": subprocess.list2cmdline(arguments), "cwd": str(root)}
    script = "$c=[Console]::In.ReadToEnd()|ConvertFrom-Json;$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut($c.link);$s.TargetPath=$c.target;$s.Arguments=$c.arguments;$s.WorkingDirectory=$c.cwd;$s.Save()"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   input=json.dumps(config), text=True, capture_output=True, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    if not link.exists():
        raise OSError("桌面快捷方式未能创建。")
    return link
