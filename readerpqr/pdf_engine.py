"""Local PDF extraction. No document or rendered image is sent to an API."""
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path

import pymupdf

from .models import Block, Paper

# MuPDF is not thread-safe. All renderer and parser access shares this lock.
PDF_LOCK = threading.RLock()


class PDFError(ValueError):
    pass


class PasswordRequired(PDFError):
    pass


def normalize_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\u00ad\n", "").replace("\u00ad", "")
    return re.sub(r"\s+", " ", text).strip()


def reading_order(blocks: list[Block], width: float, mode: str = "auto") -> list[Block]:
    """Column-aware ordering, segmented by full-width headings/captions.

    It is deliberately heuristic: the reader exposes single/two-column overrides.
    Wide separators prevent a top-of-page title from mixing body columns.
    """
    if mode == "single" or len(blocks) < 2:
        return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    middle = width / 2
    left = [b for b in blocks if b.bbox[2] <= middle + 8]
    right = [b for b in blocks if b.bbox[0] >= middle - 8]
    two_columns = mode == "double" or (
        len(left) >= 2 and len(right) >= 2
        and len(left) + len(right) >= len(blocks) * 0.65
    )
    if not two_columns:
        return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    separators = sorted(
        [b for b in blocks if b.bbox[0] < middle - 8 and b.bbox[2] > middle + 8],
        key=lambda b: b.bbox[1],
    )
    remaining = [b for b in blocks if b not in separators]
    result: list[Block] = []

    def append_columns(items: list[Block]) -> None:
        result.extend(sorted(items, key=lambda b: (
            0 if (b.bbox[0] + b.bbox[2]) / 2 < middle else 1,
            b.bbox[1], b.bbox[0],
        )))

    for separator in separators:
        band = [b for b in remaining if (b.bbox[1] + b.bbox[3]) / 2 < separator.bbox[1]]
        append_columns(band)
        remaining = [b for b in remaining if b not in band]
        result.append(separator)
    append_columns(remaining)
    return result


def load_paper(path: str, password: str = "", mode: str = "auto", cancel=None) -> Paper:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise PDFError("文件不存在或已被移动。")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if cancel and cancel.is_set():
                raise InterruptedError("导入已取消")
            digest.update(chunk)
    try:
        with PDF_LOCK, pymupdf.open(str(source)) as document:
            if not document.is_pdf:
                raise PDFError("请导入 PDF 文件。")
            if document.needs_pass and not document.authenticate(password):
                raise PasswordRequired("该 PDF 已加密，请输入正确的打开密码。")
            if document.page_count == 0:
                raise PDFError("PDF 没有可读取的页面。")
            result = Paper(str(source), digest.hexdigest(),
                           (document.metadata or {}).get("title") or source.stem,
                           document.page_count)
            for index, page in enumerate(document):
                if cancel and cancel.is_set():
                    raise InterruptedError("导入已取消")
                blocks = []
                data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
                for item in data["blocks"]:
                    if item.get("type") != 0:
                        continue
                    lines = item.get("lines", [])
                    raw = "\n".join("".join(s["text"] for s in line["spans"]) for line in lines)
                    text = normalize_text(raw)
                    if not text:
                        continue
                    fonts = [s.get("font", "").lower() for line in lines for s in line["spans"]]
                    math_fonts = sum(any(m in f for m in ("cmsy", "cmmi", "symbol", "math")) for f in fonts)
                    words = re.findall(r"[A-Za-z]{3,}", text)
                    kind = "literal" if not re.search(r"[A-Za-z]{2}", text) else "text"
                    if fonts and math_fonts > len(fonts) / 2 and len(words) < 5:
                        kind = "formula"
                    block_id = f"p{index + 1:04d}-b{len(blocks) + 1:04d}"
                    blocks.append(Block(block_id, index, tuple(item["bbox"]), text, kind))
                result.pages.append(reading_order(blocks, page.cropbox.width, mode))
                if not blocks or sum(len(b.text) for b in blocks) < 12:
                    result.image_only_pages.append(index)
            return result
    except (PDFError, InterruptedError):
        raise
    except Exception as exc:
        raise PDFError("无法解析 PDF：文件可能损坏或格式不受支持。") from exc


class Renderer:
    """Owned by the GUI thread; never share the document with a worker."""
    def __init__(self, path: str, password: str = ""):
        with PDF_LOCK:
            self.document = pymupdf.open(path)
            if self.document.needs_pass and not self.document.authenticate(password):
                self.document.close()
                raise PasswordRequired("PDF 密码不正确。")

    def png(self, page_number: int, width: int = 1000,
            bbox: tuple[float, float, float, float] | None = None) -> bytes:
        with PDF_LOCK:
            page = self.document[page_number]
            clip = pymupdf.Rect(bbox) * page.rotation_matrix if bbox else page.rect
            clip = (clip + (-2, -2, 2, 2)) & page.rect
            if clip.is_empty:
                raise PDFError("该段落没有有效的显示区域。")
            scale = min(3.0, max(0.5, width / max(clip.width, 1)))
            return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                                   alpha=False).tobytes("png")

    def boxes(self, page_number: int, blocks: list[Block]):
        with PDF_LOCK:
            page = self.document[page_number]
            rect = page.rect
            return [(b.id, tuple(pymupdf.Rect(b.bbox) * page.rotation_matrix)) for b in blocks], (rect.width, rect.height)

    def close(self):
        with PDF_LOCK:
            self.document.close()
