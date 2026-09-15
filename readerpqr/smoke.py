"""Deterministic offline checks, not a substitute for a real model-quality test."""
from pathlib import Path

import pymupdf

from .export import export_html, export_json
from .pdf_engine import load_paper
from .storage import Cache, Settings


def create_sample(path: Path):
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((42, 56), "Learning to Read Research Papers", fontsize=21)
        page.insert_text((42, 84), "Synthetic layout fixture - not a research result", fontsize=10)
        page.insert_textbox((42, 116, 280, 165), "Abstract\nAn aligned bilingual reader links every translated paragraph to the source PDF.", fontsize=11)
        page.insert_textbox((42, 190, 280, 290), "1 Introduction\nResearch papers often use two columns. Reading order and the original figures must remain accessible during translation.", fontsize=11)
        page.insert_textbox((315, 116, 553, 210), "2 Method\nThe local parser extracts text and bounding boxes. A language model translates structured blocks with stable identifiers.", fontsize=11)
        page.insert_textbox((315, 250, 553, 350), "3 Reliability\nCompleted paragraphs are cached on disk. Cancelling a request preserves previous results without accepting incomplete output.", fontsize=11)
        page.draw_rect((42, 385, 553, 515), color=(0.15, 0.4, 0.4), fill=(0.94, 0.97, 0.97))
        page.insert_text((60, 430), "PDF  ->  Local text blocks  ->  AI translation", fontsize=14)
        page.insert_text((60, 465), "Original page + linked Chinese paragraphs", fontsize=13)
        page.insert_textbox((42, 535, 553, 595), "Figure 1. A synthetic pipeline used only to exercise layout, rendering and navigation. No model output is presented as an experiment.", fontsize=10)
        page2 = doc.new_page()
        page2.insert_text((42, 65), "Appendix - offline verification", fontsize=18)
        page2.insert_textbox((42, 105, 500, 210), "The application validates block identifiers and protects numeric citations such as [1, 2]. It never silently treats an empty result as a translation.", fontsize=12)
        doc.set_metadata({"title": "双语文献阅读示例 · 离线界面测试"})
        doc.save(str(path))


def run_smoke(output: Path):
    from PySide6.QtWidgets import QApplication
    from .ui import ReaderWindow
    source = output / "synthetic-paper.pdf"
    create_sample(source)
    paper = load_paper(str(source))
    assert paper.page_count == 2 and len(paper.blocks) >= 5
    settings = Settings(auto_translate=False)
    # Explicitly labeled placeholders: test output never enters a user's cache.
    with Cache() as cache:
        for block in paper.blocks:
            if block.kind == "text":
                cache.put(paper.fingerprint, settings.profile_id(), block.id, block.text,
                          "【离线测试占位，非 AI 翻译】每一段中文与对应原文共享一行。原文截图保留公式和排版；点击原页定位可核对上下文。")
    window = ReaderWindow(settings)
    window.paper_loaded(paper)
    window.show()
    QApplication.processEvents()
    assert window.translation_labels
    identity = paper.pages[0][0].id
    window.focus_block(identity)
    QApplication.processEvents()
    assert window.page_image.active == identity
    window.tabs.setCurrentIndex(0)
    export_html(paper, window.translations, str(output / "bilingual.html"))
    export_json(paper, window.translations, str(output / "blocks.json"))
    return window
