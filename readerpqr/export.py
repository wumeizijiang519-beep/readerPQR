"""Offline, script-free exports. PDF and AI strings are always HTML-escaped."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .models import Paper


def export_html(paper: Paper, translations: dict[str, str], path: str):
    esc = lambda value: html.escape(str(value), quote=True)
    pages = []
    for index, blocks in enumerate(paper.pages):
        rows = []
        for block in blocks:
            value = translations.get(block.id)
            if value is None and block.kind != "text":
                value = block.text
            right = value if value is not None else "【尚未翻译】"
            rows.append(f'<tr id="{esc(block.id)}"><td><small>{esc(block.id)}</small><p>{esc(block.text)}</p></td>'
                        f'<td><p>{esc(right)}</p></td></tr>')
        pages.append(f'<section><h2>第 {index + 1} 页</h2><table><thead><tr><th>原文</th><th>中文</th></tr></thead><tbody>{"".join(rows)}</tbody></table></section>')
    content = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
               f'<title>{esc(paper.title)} · readerPQR</title><style>'
               'body{font:16px/1.85 "Microsoft YaHei",sans-serif;max-width:1300px;margin:40px auto;padding:0 24px;color:#1c2935}'
               'h1{font-size:30px}h2{font-size:20px}small{color:#667781}table{width:100%;border-collapse:collapse;table-layout:fixed}'
               'td,th{width:50%;padding:14px 20px;border:1px solid #d8e2e7;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}'
               'th{background:#f0f5f5}p{margin:0}section{margin-top:32px}tr{break-inside:avoid}'
               '@media print{body{margin:0;font-size:10pt}section{break-before:page}}'
               '</style></head><body>'
               f'<h1>{esc(paper.title)}</h1><p>readerPQR · AI 译文仅供辅助阅读，请核对原文。此文件为文字对照导出，不重建原 PDF 的图片与公式排版。</p>'
               + ''.join(pages) + '</body></html>')
    Path(path).write_text(content, encoding="utf-8")


def export_json(paper: Paper, translations: dict[str, str], path: str):
    payload = {"schema_version": 1, "title": paper.title, "sha256": paper.fingerprint,
               "pages": [[{"id": b.id, "bbox": b.bbox, "kind": b.kind,
                           "source": b.text, "translation": translations.get(b.id)}
                          for b in blocks] for blocks in paper.pages]}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
