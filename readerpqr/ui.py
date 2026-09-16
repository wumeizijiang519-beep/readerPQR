from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .dialogs import SettingsDialog
from .export import export_html, export_json
from .pdf_engine import Renderer, load_paper
from .storage import Cache, Settings, endpoint_url, load_settings
from .style import STYLE
from .translate import translate_paper
from .workers import Task


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    if name:
        result.setObjectName(name)
    result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return result


def scroll_content():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    scroll.setWidget(widget)
    return scroll, widget, layout


class PageImage(QWidget):
    selected = Signal(str)

    def __init__(self, png: bytes, boxes=None, page_size=None, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.pixmap.loadFromData(png, "PNG")
        self.boxes = boxes or []
        self.page_size = page_size or (self.pixmap.width(), self.pixmap.height())
        self.active = ""
        self.setMouseTracking(True)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(1, round(width * self.pixmap.height() / max(1, self.pixmap.width())))

    def sizeHint(self):
        return QSize(500, self.heightForWidth(500))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        target = QRectF(0, 0, self.width(), self.heightForWidth(self.width()))
        painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.active:
            for identity, box in self.boxes:
                if identity != self.active:
                    continue
                sx, sy = target.width() / self.page_size[0], target.height() / self.page_size[1]
                rectangle = QRectF(box[0] * sx, box[1] * sy, (box[2] - box[0]) * sx, (box[3] - box[1]) * sy)
                painter.setPen(QPen(QColor("#208775"), 2))
                painter.setBrush(QColor(40, 160, 125, 35))
                painter.drawRect(rectangle)

    def mousePressEvent(self, event):
        point = event.position()
        x = point.x() / max(1, self.width()) * self.page_size[0]
        y = point.y() / max(1, self.heightForWidth(self.width())) * self.page_size[1]
        for identity, box in self.boxes:
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                self.active = identity
                self.update()
                self.selected.emit(identity)
                break
        super().mousePressEvent(event)

    def focus_block(self, identity):
        self.active = identity
        self.update()
        for key, box in self.boxes:
            if key == identity:
                return int(box[1] / self.page_size[1] * self.heightForWidth(self.width()))
        return 0


class ReaderWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.setWindowTitle("readerPQR · AI 文献阅读器")
        self.resize(1440, 900)
        self.setMinimumSize(1050, 680)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        warning = ""
        try:
            self.settings = settings or load_settings()
        except Exception:
            self.settings = Settings()
            warning = "原设置文件无法读取，已使用默认设置；请重新填写 API。"
        self.paper = None
        self.qa_history = []
        self.qa_dialog = None
        self.qa_windows = set()
        self.renderer = None
        self.password = ""
        self.translations = {}
        self.translation_labels = {}
        self.right_cards = {}
        self.aligned_cards = {}
        self.page_image = None
        self.task = None
        self.after_task = None
        self.closing = False
        self.seen = set()
        self._search_term = ""
        self._search_index = -1
        self._build()
        self._actions()
        self._enable(False)
        self.statusBar().showMessage(warning or "就绪 · PDF 在本地解析，API 仅在授权后调用。")

    def _build(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 26, 20, 18)
        side.addWidget(label("readerPQR", "brand"))
        side.addWidget(label("AI · BILINGUAL READER", "eyebrow"))
        side.addSpacing(26)
        self.import_button = QPushButton("＋  导入 PDF")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self.choose_pdf)
        side.addWidget(self.import_button)
        side.addSpacing(16)
        self.document_label = label("尚未导入文献", wrap=True)
        side.addWidget(self.document_label)
        side.addSpacing(12)
        side.addWidget(label("页面导航", "eyebrow"))
        self.pages = QListWidget()
        self.pages.currentRowChanged.connect(self.go_page)
        side.addWidget(self.pages, 1)
        side.addWidget(label("原文始终保留在本机\n译文按段落自动缓存", wrap=True))
        self.settings_button = QPushButton("AI 设置与术语表")
        self.settings_button.clicked.connect(self.open_settings)
        side.addWidget(self.settings_button)
        self.qa_button = QPushButton("论文问答")
        self.qa_button.clicked.connect(self.open_qa)
        side.addWidget(self.qa_button)
        self.support_button = QPushButton("支持作者 / 自愿打赏")
        self.support_button.clicked.connect(self.open_support)
        side.addWidget(self.support_button)
        outer.addWidget(sidebar)
        body = QWidget()
        main = QVBoxLayout(body)
        main.setContentsMargins(24, 20, 24, 14)
        main.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(label("文献阅读", "title"))
        top.addStretch()
        self.find = QLineEdit()
        self.find.setPlaceholderText("搜索原文 / 中文，回车定位下一处")
        self.find.setMinimumWidth(270)
        self.find.returnPressed.connect(self.search)
        top.addWidget(self.find)
        self.export_button = QPushButton("导出双语")
        self.export_button.clicked.connect(self.export)
        top.addWidget(self.export_button)
        self.shortcut_button = QPushButton("创建桌面阅读快捷方式")
        self.shortcut_button.clicked.connect(self.create_reading_shortcut)
        top.addWidget(self.shortcut_button)
        main.addLayout(top)
        self.notice = label("导入英文论文，生成逐段对齐的中文译文。原页、公式与图表随时可核对。", "notice", True)
        main.addWidget(self.notice)
        tools = QHBoxLayout()
        self.previous = QPushButton("‹")
        self.previous.clicked.connect(lambda: self.page_number.setValue(self.page_number.value() - 1))
        self.page_number = QSpinBox()
        self.page_number.setMinimum(1)
        self.page_number.setMaximum(1)
        self.page_number.setPrefix("第 ")
        self.page_number.setSuffix(" 页")
        self.page_number.valueChanged.connect(lambda value: self.pages.setCurrentRow(value - 1))
        self.next_button = QPushButton("›")
        self.next_button.clicked.connect(lambda: self.page_number.setValue(self.page_number.value() + 1))
        for widget in (self.previous, self.page_number, self.next_button):
            tools.addWidget(widget)
        tools.addSpacing(10)
        self.order = QComboBox()
        self.order.addItems(["自动识别分栏", "按单栏阅读", "按双栏阅读"])
        self.order.currentIndexChanged.connect(self.change_order)
        tools.addWidget(self.order)
        tools.addStretch()
        self.page_translate = QPushButton("翻译本页")
        self.page_translate.clicked.connect(lambda: self.start_translation([self.current_page]))
        self.translate_button = QPushButton("翻译全文 / 继续")
        self.translate_button.setObjectName("primary")
        self.translate_button.clicked.connect(lambda: self.start_translation())
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop)
        for widget in (self.page_translate, self.translate_button, self.stop_button):
            tools.addWidget(widget)
        main.addLayout(tools)
        self.tabs = QTabWidget()
        self.aligned_scroll, self.aligned_body, self.aligned_layout = scroll_content()
        self.tabs.addTab(self.aligned_scroll, "逐段对齐")
        self.original_split = QSplitter(Qt.Orientation.Horizontal)
        self.original_scroll, self.original_body, self.original_layout = scroll_content()
        self.right_scroll, self.right_body, self.right_layout = scroll_content()
        self.original_split.addWidget(self.original_scroll)
        self.original_split.addWidget(self.right_scroll)
        self.original_split.setSizes([650, 480])
        self.tabs.addTab(self.original_split, "原页定位")
        main.addWidget(self.tabs, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        main.addWidget(self.progress)
        bottom = QHBoxLayout()
        bottom.addWidget(label("PDF 本地处理  ·  段落级缓存", "muted"))
        bottom.addStretch()
        bottom.addWidget(label("AI 翻译仅供辅助，请核对原文", "muted"))
        main.addLayout(bottom)
        main.addWidget(label("制作人：彭先生 pengqianrang2026@ia.ac.cn", "muted", True))
        outer.addWidget(body, 1)
        welcome = label("把 PDF 拖到这里\n\n或点击左侧「导入 PDF」\n\n首次使用请在「AI 设置与术语表」中填写接口和密钥。", "title", True)
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.aligned_layout.addStretch()
        self.aligned_layout.addWidget(welcome)
        self.aligned_layout.addStretch()

    def _actions(self):
        for shortcut, callback in ((QKeySequence.StandardKey.Open, self.choose_pdf),
                                   (QKeySequence.StandardKey.Find, self.find.setFocus)):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    @property
    def current_page(self):
        return max(0, self.pages.currentRow())

    def _enable(self, busy):
        present = self.paper is not None
        self.qa_button.setEnabled(present)
        self.shortcut_button.setEnabled(present and not busy)
        for widget in (self.import_button, self.settings_button):
            widget.setEnabled(not busy)
        for widget in (self.translate_button, self.page_translate, self.order):
            widget.setEnabled(present and not busy)
        for widget in (self.previous, self.next_button, self.page_number, self.pages, self.find, self.export_button):
            widget.setEnabled(present)
        self.stop_button.setEnabled(busy)

    def choose_pdf(self):
        if self.task is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入文献", "", "PDF 文件 (*.pdf)")
        if path:
            self.open_path(path)

    def open_path(self, path, password=""):
        if self.task is not None:
            self.statusBar().showMessage("请先停止当前任务，再导入其他 PDF。")
            return
        self.password = password
        mode = ["auto", "single", "double"][self.order.currentIndex()]
        task = Task(lambda t: load_paper(path, password, mode, t.stop), self)
        self._start_task(task, self.paper_loaded)
        for widget in (self.pages, self.page_number, self.previous, self.next_button, self.find, self.export_button):
            widget.setEnabled(False)
        self.tabs.setEnabled(False)
        self.qa_button.setEnabled(False)
        task.failed.disconnect(self._failure)
        task.failed.connect(lambda kind, message: self._import_failure(kind, message, path))
        self.progress.setRange(0, 0)
        self.notice.setText("正在本地解析 PDF 与页面布局…")

    def _import_failure(self, kind, message, path):
        self._failure(kind, message)
        if kind == "PasswordRequired":
            def ask():
                password, ok = QInputDialog.getText(self, "加密 PDF", "请输入 PDF 打开密码（不保存）：", QLineEdit.EchoMode.Password)
                if ok:
                    self.open_path(path, password)
            self.after_task = ask

    def _start_task(self, task, success):
        self.task = task
        self._enable(True)
        task.result.connect(success)
        task.failed.connect(self._failure)
        task.finished.connect(self._finished)
        task.finished.connect(task.deleteLater)
        task.start()

    def _failure(self, kind, message):
        self.notice.setText(message)
        self.statusBar().showMessage(message)

    def _finished(self):
        self.task = None
        self._enable(False)
        self.tabs.setEnabled(True)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        callback, self.after_task = self.after_task, None
        if self.closing:
            QTimer.singleShot(0, self.close)
        elif callback:
            QTimer.singleShot(0, callback)

    def paper_loaded(self, paper):
        if self.paper is None or self.paper.fingerprint != paper.fingerprint:
            if self.qa_dialog is not None:
                self.qa_dialog.reject()
                self.qa_dialog = None
            self.qa_history = []
        if self.renderer is not None:
            self.renderer.close()
        self.renderer = Renderer(paper.path, self.password)
        self.paper = paper
        self.document_label.setText(paper.title)
        self.setWindowTitle(f"{paper.title} — readerPQR")
        self._read_cache()
        self.pages.blockSignals(True)
        self.pages.clear()
        for i, blocks in enumerate(paper.pages):
            flag = " · 待 OCR" if i in paper.image_only_pages else f" · {len(blocks)} 段"
            self.pages.addItem(f"{i + 1:02d}  /  第 {i + 1} 页{flag}")
        self.pages.blockSignals(False)
        self.page_number.setMaximum(paper.page_count)
        self.pages.setCurrentRow(0)
        self._enable(self.task is not None)
        chars = sum(len(b.text) for b in paper.blocks if b.kind == "text")
        self.notice.setText(f"已导入 {paper.page_count} 页 · 约 {chars:,} 个待译原文字符。译文逐段对齐，公式与图表请对照原页。")
        if paper.image_only_pages:
            numbers = ", ".join(str(i + 1) for i in paper.image_only_pages[:20])
            self.notice.setText(f"第 {numbers} 页文字层缺失或过少；这些页面可能需要 OCR。此版本不自动识别扫描图片中的文字。")
        if self.settings.auto_translate and self._ready() and any(b.kind == "text" for b in paper.blocks):
            self.after_task = lambda: self.start_translation()
        elif not self._ready():
            self.statusBar().showMessage("原文已可阅读。请打开 AI 设置，填写接口并确认发送许可后翻译。")

    def _read_cache(self):
        self.translations = {}
        if not self.paper:
            return
        with Cache() as cache:
            profile = self.settings.profile_id()
            for block in self.paper.blocks:
                if block.kind != "text":
                    self.translations[block.id] = block.text
                else:
                    value = cache.get(self.paper.fingerprint, profile, block.id, block.text)
                    if value is not None:
                        self.translations[block.id] = value

    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def go_page(self, index):
        if not self.paper or index < 0 or index >= self.paper.page_count:
            return
        self.page_number.blockSignals(True)
        self.page_number.setValue(index + 1)
        self.page_number.blockSignals(False)
        self.translation_labels = {}
        self.aligned_cards = {}
        self.right_cards = {}
        for layout in (self.aligned_layout, self.original_layout, self.right_layout):
            self._clear(layout)
        blocks = self.paper.pages[index]
        boxes, page_size = self.renderer.boxes(index, blocks)
        self.page_image = PageImage(self.renderer.png(index, 1300), boxes, page_size)
        self.page_image.selected.connect(lambda identity: self.focus_block(identity, False))
        self.original_layout.addWidget(self.page_image)
        self.original_layout.addStretch()
        if not blocks:
            self.aligned_layout.addWidget(label("本页没有可提取的文字。请在「原页定位」查看，或先用 OCR 工具生成可搜索 PDF。", wrap=True))
        for block in blocks:
            row = QFrame()
            row.setObjectName("row")
            columns = QHBoxLayout(row)
            columns.setContentsMargins(16, 14, 16, 16)
            columns.setSpacing(24)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            header = QHBoxLayout()
            header.addWidget(label(f"原文 · {block.id}", "muted"))
            header.addStretch()
            locate = QPushButton("原页定位")
            locate.clicked.connect(lambda checked=False, identity=block.id: self.focus_block(identity))
            header.addWidget(locate)
            left_layout.addLayout(header)
            try:
                left_layout.addWidget(PageImage(self.renderer.png(index, 1050, block.bbox)))
            except Exception:
                left_layout.addWidget(label(block.text, wrap=True))
            copy_source = QPushButton("复制原文")
            copy_source.clicked.connect(lambda checked=False, text=block.text: QApplication.clipboard().setText(text))
            left_layout.addWidget(copy_source, 0, Qt.AlignmentFlag.AlignLeft)
            left_layout.addStretch()
            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.addWidget(label("中文译文" if block.kind == "text" else "公式 / 数字 · 保留原文", "muted"))
            text = self.translations.get(block.id, "等待翻译…")
            translated = label(text, "translationText", True)
            right_layout.addWidget(translated)
            copy_translation = QPushButton("复制译文")
            copy_translation.clicked.connect(lambda checked=False, identity=block.id: QApplication.clipboard().setText(self.translations.get(identity, "")))
            right_layout.addWidget(copy_translation, 0, Qt.AlignmentFlag.AlignLeft)
            right_layout.addStretch()
            columns.addWidget(left, 1)
            columns.addWidget(right, 1)
            self.aligned_layout.addWidget(row)
            self.aligned_cards[block.id] = row
            card = QFrame()
            card.setObjectName("translation")
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(label(block.id, "muted"))
            translated2 = label(text, "translationText", True)
            card_layout.addWidget(translated2)
            focus = QPushButton("定位原文")
            focus.clicked.connect(lambda checked=False, identity=block.id: self.focus_block(identity))
            card_layout.addWidget(focus, 0, Qt.AlignmentFlag.AlignLeft)
            self.right_layout.addWidget(card)
            self.right_cards[block.id] = card
            self.translation_labels[block.id] = [translated, translated2]
        self.aligned_layout.addStretch()
        self.right_layout.addStretch()
        self.aligned_scroll.verticalScrollBar().setValue(0)
        self.original_scroll.verticalScrollBar().setValue(0)
        self.right_scroll.verticalScrollBar().setValue(0)

    def focus_block(self, identity, show_original=True):
        if show_original:
            self.tabs.setCurrentIndex(1)
        if self.page_image:
            y = self.page_image.focus_block(identity)
            self.original_scroll.ensureVisible(0, y, 0, 80)
        if identity in self.right_cards:
            self.right_scroll.ensureWidgetVisible(self.right_cards[identity], 0, 40)
        if identity in self.aligned_cards:
            self.aligned_scroll.ensureWidgetVisible(self.aligned_cards[identity], 0, 20)

    def _ready(self):
        endpoint = endpoint_url(self.settings.base_url)
        local = urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
        return self.settings.consent_endpoint == endpoint and (bool(self.settings.api_key) or local)

    def start_translation(self, pages=None):
        if not self.paper or self.task is not None:
            return
        if not self._ready():
            QMessageBox.information(self, "先配置 AI", "请在 AI 设置中填写接口与密钥，并确认允许向该地址发送文献文字。")
            self.open_settings()
            return
        total = sum(len(self.paper.pages[i]) for i in (pages if pages is not None else range(self.paper.page_count)))
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.seen = set()
        task = Task(lambda t: asyncio.run(translate_paper(
            self.paper, self.settings, t.stop, t.translated.emit, t.block_failed.emit, pages)), self)
        task.translated.connect(self.receive_translation)
        task.block_failed.connect(self.receive_failure)
        self._start_task(task, self.translation_done)
        self.notice.setText("正在生成中文译文… 已有缓存会自动跳过，你可以继续翻页阅读。")

    def receive_translation(self, identity, text, state):
        self.translations[identity] = text
        self.seen.add(identity)
        self.progress.setValue(len(self.seen))
        for widget in self.translation_labels.get(identity, []):
            widget.setText(text)
        self.statusBar().showMessage(f"{state} · {identity} · 已处理 {len(self.seen)} / {self.progress.maximum()} 段")

    def receive_failure(self, identity, message):
        self.seen.add(identity)
        self.progress.setValue(len(self.seen))
        for widget in self.translation_labels.get(identity, []):
            widget.setText("翻译失败，可点击「翻译本页」重试。\n" + message)
        self.statusBar().showMessage(f"{identity}：{message}")

    def translation_done(self, stats):
        self.notice.setText(f"处理完成 · 新翻译 {stats['translated']} 段 · 缓存 {stats['cached']} 段 · 保留原文 {stats['preserved']} 段 · 失败 {stats['failed']} 段。")

    def stop(self):
        if self.task is not None:
            self.task.stop.set()
            self.stop_button.setEnabled(False)
            self.notice.setText("正在停止；已完成的译文会保留，之后可以继续。")

    def open_settings(self):
        if self.task is not None:
            return
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.settings
            if self.qa_dialog is not None:
                self.qa_dialog.set_settings(self.settings)
            self._read_cache()
            if self.paper:
                self.go_page(self.current_page)
            self.statusBar().showMessage("设置已保存。模型或术语变化时将使用独立缓存。")
            if self.paper and self.settings.auto_translate and self._ready():
                self.start_translation()

    def change_order(self):
        if self.paper and self.task is None:
            self.open_path(self.paper.path, self.password)

    def search(self):
        if not self.paper:
            return
        term = self.find.text().strip().casefold()
        if not term:
            return
        matches = [b for b in self.paper.blocks if term in b.text.casefold() or term in self.translations.get(b.id, "").casefold()]
        if not matches:
            self.statusBar().showMessage("未找到匹配内容。")
            return
        self._search_index = (self._search_index + 1) % len(matches) if term == self._search_term else 0
        self._search_term = term
        block = matches[self._search_index]
        self.pages.setCurrentRow(block.page)
        self.focus_block(block.id)
        self.statusBar().showMessage(f"匹配 {self._search_index + 1} / {len(matches)} · {block.id}")

    def open_qa(self):
        if self.paper is None or not self.tabs.isEnabled():
            return
        if self.qa_dialog is not None:
            self.qa_dialog.showNormal()
            self.qa_dialog.raise_()
            self.qa_dialog.activateWindow()
            return
        if not self._ready():
            QMessageBox.information(self, "先配置 AI", "请在 AI 设置中填写接口与密钥，并确认允许发送论文文字，再打开论文问答。")
            return
        from .qa_dialog import PaperQADialog
        dialog = PaperQADialog(self.paper, self.settings, self.qa_history, self.current_page, self)
        self.qa_dialog = dialog
        self.qa_windows.add(dialog)
        dialog.finished.connect(lambda _: self._qa_closed(dialog))
        dialog.show()

    def _qa_closed(self, dialog):
        self.qa_windows.discard(dialog)
        if self.qa_dialog is dialog:
            self.qa_dialog = None
        dialog.deleteLater()
        if self.closing:
            QTimer.singleShot(0, self.close)

    def open_support(self):
        from .support import SupportDialog
        SupportDialog(self).exec()

    def create_reading_shortcut(self):
        if not self.paper or self.task is not None:
            return
        if self.password:
            QMessageBox.warning(self, "无法创建", "此 PDF 需要密码。请先使用已解密的 PDF；快捷方式不会保存 PDF 密码。")
            return
        try:
            from .reading_snapshot import save_snapshot, create_shortcut
            path = save_snapshot(self.paper, self.translations, self.current_page)
            link = create_shortcut(path, self.paper.title)
            total = sum(b.kind == "text" for b in self.paper.blocks)
            done = sum(b.kind == "text" and bool(self.translations.get(b.id)) for b in self.paper.blocks)
            QMessageBox.information(self, "阅读快捷方式已创建",
                f"已保存 PDF 副本、当前译文（{done}/{total} 段）和阅读页码。\n\n桌面快捷方式：\n{link}\n\n双击即可离线阅读，无需 API 密钥。后续译文更新后，请重新创建快捷方式。")
        except Exception:
            QMessageBox.warning(self, "创建失败", "无法保存阅读快照或创建桌面快捷方式，请检查磁盘空间和文件访问权限。")

    def open_reading_snapshot(self, path):
        from dataclasses import replace
        from .reading_snapshot import load_snapshot
        paper, translations, page = load_snapshot(path)
        self.settings = replace(self.settings, auto_translate=False)
        self.paper_loaded(paper)
        self.translations.update(translations)
        self.pages.setCurrentRow(page)
        self.go_page(page)
        self.order.setEnabled(False)
        total = sum(b.kind == "text" for b in paper.blocks)
        done = sum(b.kind == "text" and bool(translations.get(b.id)) for b in paper.blocks)
        self.notice.setText(f"已打开阅读快照 · {paper.page_count} 页 · 已保存译文 {done}/{total} 段 · 离线阅读")
        self.statusBar().showMessage("已恢复保存时的译文和阅读页码，无需调用 API。")

    def export(self):
        if not self.paper:
            return
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.paper.title)[:100]
        path, selected = QFileDialog.getSaveFileName(self, "导出双语对照", name + "_双语.html", "双语 HTML (*.html);;段落数据 JSON (*.json)")
        if not path:
            return
        suffix = ".json" if "JSON" in selected else ".html"
        if not path.lower().endswith(suffix):
            path += suffix
        if Path(path).resolve() == Path(self.paper.path).resolve():
            QMessageBox.warning(self, "无法导出", "不能覆盖原始 PDF。")
            return
        try:
            (export_json if suffix == ".json" else export_html)(self.paper, self.translations, path)
            self.statusBar().showMessage("导出完成。HTML 可离线打开，也可在浏览器打印为 PDF（文字对照版）。")
        except OSError:
            QMessageBox.warning(self, "导出失败", "无法写入所选目录，请检查权限和磁盘空间。")

    def dragEnterEvent(self, event):
        if self.task is None and any(u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
                self.open_path(url.toLocalFile())
                event.acceptProposedAction()
                break

    def closeEvent(self, event):
        qa_busy = any(dialog.task is not None for dialog in self.qa_windows)
        if self.task is not None or qa_busy:
            if not self.closing:
                answer = QMessageBox.question(self, "停止后退出？", "正在处理文献或生成问答。停止任务并退出吗？已完成的译文会保留。")
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self.closing = True
            if self.task is not None:
                self.task.stop.set()
            for dialog in list(self.qa_windows):
                dialog.reject()
            event.ignore()
            return
        for dialog in list(self.qa_windows):
            dialog.reject()
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        event.accept()
