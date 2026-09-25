"""Local attachment extraction; original paths never enter API payloads."""
from pathlib import Path
import threading
import base64
import fitz
from .translate import Cancelled

MAX_FILES = 5
MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 120000
EXTENSIONS = {'.pdf', '.txt', '.md', '.csv', '.png', '.jpg', '.jpeg'}


def validate_paths(paths):
    paths = tuple(dict.fromkeys(str(Path(p).resolve()) for p in paths))
    if len(paths) > MAX_FILES:
        raise ValueError('最多添加5个附件。')
    for name in paths:
        p = Path(name)
        if p.suffix.lower() not in EXTENSIONS:
            raise ValueError('附件支持 PDF、TXT、Markdown、CSV、PNG 和 JPG。')
        if not p.is_file():
            raise ValueError('附件不存在或不可读取，请重新选择。')
        if p.stat().st_size > MAX_BYTES:
            raise ValueError('单个附件不能超过10 MB。')
    return paths


def load_attachments(paths, stop=None):
    stop = stop or threading.Event()
    rows = []
    total = 0
    image_count = 0
    image_bytes = 0

    def render(page, page_number):
        nonlocal image_count, image_bytes
        image_count += 1
        if image_count > 20:
            raise ValueError('单次最多发送20张图片或PDF图像页，请拆分附件。')
        scale = min(2, 1600 / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        encoded = base64.b64encode(pix.tobytes('jpeg', jpg_quality=90)).decode('ascii')
        image_bytes += len(encoded)
        if image_bytes > 20 * 1024 * 1024:
            raise ValueError('附件图像数据超过20 MB，请减少附件。')
        return {'page': page_number, 'url': 'data:image/jpeg;base64,' + encoded}

    for index, name in enumerate(validate_paths(paths), 1):
        if stop.is_set():
            raise Cancelled('已停止读取附件。')
        p = Path(name)
        try:
            raw = p.read_bytes()
            if len(raw) > MAX_BYTES:
                raise ValueError('单个附件不能超过10 MB。')
            images = []
            if p.suffix.lower() == '.pdf':
                sections = []
                with fitz.open(stream=raw, filetype='pdf') as doc:
                    if doc.needs_pass:
                        raise ValueError('附件PDF需要密码，请先解密。')
                    for page in doc:
                        if stop.is_set():
                            raise Cancelled('已停止读取附件。')
                        text = page.get_text().strip()
                        # Include scans (even with an OCR layer), diagrams and sparse pages.
                        if len(text) < 80 or page.get_images() or page.get_drawings():
                            images.append(render(page, page.number + 1))
                        total += len(text)
                        if total > MAX_CHARS:
                            raise ValueError('附件文字超过120,000字符，请减少附件。')
                        if text:
                            sections.append(f'[第{page.number + 1}页]\n{text}')
                text = '\n\n'.join(sections)
            elif p.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
                with fitz.open(stream=raw, filetype=p.suffix[1:]) as doc:
                    images.append(render(doc[0], 1))
                text = ''
            else:
                text = None
                for encoding in ('utf-8-sig', 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'gb18030'):
                    try:
                        text = raw.decode(encoding)
                        break
                    except UnicodeError:
                        pass
                if text is None or '\x00' in text:
                    raise ValueError('附件编码无法识别，请转换为UTF-8文本。')
                total += len(text)
            if not text.strip() and not images:
                raise ValueError('附件没有可提取文字；扫描PDF需要先进行OCR。')
            if total > MAX_CHARS:
                raise ValueError('附件文字超过120,000字符，请减少附件。')
            row = {'id': f'附件{index}', 'name': p.name, 'text': text}
            if images:
                row['images'] = images
            rows.append(row)
        except (OSError, fitz.FileDataError, fitz.EmptyFileError, fitz.mupdf.FzErrorBase):
            raise ValueError('附件无法读取或已损坏，请重新选择。') from None
    return rows
