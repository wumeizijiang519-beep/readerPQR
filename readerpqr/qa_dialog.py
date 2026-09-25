import asyncio
import time
from dataclasses import replace
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QListWidget, QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from .qa import ask_paper, paper_context
from .workers import Task
from .attachments import validate_paths
from pathlib import Path


SUMMARY_PROMPT = """请基于整篇论文，生成结构清晰的中文论文总结，严格使用以下五个标题：
一、论文议题：研究问题、背景、问题为何重要。
二、论文重点：核心方法、关键机制、主要贡献，与已有工作的区别。
三、实验结果：数据集/任务、实验设置、对照基线、关键定量结果和消融；数字注明指标、单位、比较对象及PDF页码。无实验的论文明确说明，并归纳其论证依据。
四、结论：作者的主要结论、适用范围、局限与未解决问题。
五、对本人的启示：结合下述个人背景，给出3条具体可执行的学习/研究建议，每条包括论文依据、行动与验证方式。将你的建议和推断与作者结论明确区分；背景为空时按一般论文读者给建议，不臆测个人经历或资源。
详细但避免重复，建议1200–1800中文字。论文事实引用[第N页]；无法从文字确认的图表、数字或结论明确说明，不编造。个人背景仅用于调整建议，不改变上述五部分结构。
个人背景：
"""


class PaperQADialog(QDialog):
    def __init__(self, paper, settings, history, page=0, parent=None, summary=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.summary = summary
        self.paper, self.settings, self.history = paper, settings, history
        self.attachments = ()
        self.task = None
        self.pending_question = ""
        self.partial_answer = ""
        self.request_status = "正在发送论文"
        self.close_when_stopped = False
        self.wait_timer = QTimer(self)
        self.wait_timer.setInterval(1000)
        self.wait_timer.timeout.connect(self.update_wait_status)
        self.setWindowTitle(("论文总结 · " if summary else "论文问答 · ") + paper.title)
        self.resize(850, 720)
        layout = QVBoxLayout(self)
        heading = QLabel(("论文总结" if summary else "论文问答") + " · 使用已配置的 AI 接口")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.set_settings(settings)
        layout.addWidget(self.note)
        scope = QHBoxLayout()
        scope.addWidget(QLabel("总结范围" if summary else "提问范围"))
        self.scope = QComboBox()
        self.scope.addItems(["整篇论文"] if summary else ["整篇论文", "指定页"])
        scope.addWidget(self.scope)
        self.page = QSpinBox()
        self.page.setRange(1, paper.page_count)
        self.page.setValue(page + 1)
        self.page.setPrefix("第 ")
        self.page.setSuffix(" 页")
        self.page.setEnabled(False)
        scope.addWidget(self.page)
        self.page.setVisible(not summary)
        self.context_label = QLabel()
        scope.addWidget(self.context_label, 1)
        layout.addLayout(scope)
        limits = QHBoxLayout()
        limits.addWidget(QLabel("生成总时限" if summary else "问答等待总时限"))
        self.timeout = QSpinBox()
        self.timeout.setRange(30, 300)
        self.timeout.setSuffix(" 秒")
        self.timeout.setValue(300)
        limits.addWidget(self.timeout)
        self.streaming = QCheckBox("流式显示")
        self.streaming.setChecked(True)
        limits.addWidget(self.streaming)
        limits.addWidget(QLabel("单次提交，不自动重发；输出中断 60 秒提示错误。"), 1)
        layout.addLayout(limits)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("例如：这篇论文的核心贡献是什么？实验如何验证方法有效？")
        layout.addWidget(self.transcript, 1)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("输入论文相关问题，也可以继续追问上一个回答…")
        if summary:
            self.transcript.setPlaceholderText("论文议题 · 论文重点 · 实验结果 · 结论 · 对本人的启示")
            layout.addWidget(QLabel("个人背景与关注点（可选，用于生成对本人的启示）："))
            self.question.setPlaceholderText("例如：研一，具身智能方向，希望找到可复现的小课题；每周有10小时。留空则按一般读者总结。")
        self.question.setMaximumHeight(100)
        layout.addWidget(self.question)
        self.attachment_list = QListWidget()
        self.attachment_list.setMaximumHeight(76)
        self.attachment_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.add_attachment = QPushButton("添加附件")
        self.remove_attachment = QPushButton("移除选中附件")
        self.add_attachment.clicked.connect(self.choose_attachments)
        self.remove_attachment.clicked.connect(self.remove_attachments)
        if not summary:
            attachment_row = QHBoxLayout()
            attachment_row.addWidget(self.add_attachment)
            attachment_row.addWidget(self.remove_attachment)
            attachment_row.addWidget(QLabel("PDF/图片/TXT/MD/CSV · 最多5个 · 每个≤10 MB"))
            layout.addLayout(attachment_row)
            layout.addWidget(self.attachment_list)
            layout.addWidget(QLabel("附件文字及图片/扫描页随问题发给API识别；最多20张图像页，需要模型支持识图。"))
        else:
            self.attachment_list.hide()
            self.add_attachment.hide()
            self.remove_attachment.hide()
        self.status = QLabel("总结仅保留在本次程序运行中，可复制保存。" if summary else "问答记录仅保留在本次程序运行中，可复制回答保存。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.send = QPushButton("生成论文总结" if summary else "发送问题")
        self.send.setObjectName("primary")
        self.send.clicked.connect(self.submit)
        self.stop = QPushButton("停止回答")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        self.copy = QPushButton("复制总结" if summary else "复制最近回答")
        self.copy.clicked.connect(self.copy_answer)
        self.clear = QPushButton("清空总结" if summary else "清空对话")
        self.clear.clicked.connect(self.clear_history)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        for button in (self.send, self.stop, self.copy, self.clear, close):
            row.addWidget(button)
        layout.addLayout(row)
        self.scope.currentIndexChanged.connect(self.update_scope)
        self.page.valueChanged.connect(self.update_scope)
        self.update_scope()
        self.render_history()

    def set_settings(self, settings):
        self.settings = settings
        self.note.setText(f"模型：{settings.model}  ·  服务：{urlsplit(settings.base_url).hostname}\n"
                          "可同时操作主界面；设置修改对下一次提问生效。\n"
                          "发送问题、所选论文原文、附件文字及图像和最近两轮问答，可能产生 API 费用。\n"
                          "主论文使用提取文字；附件可识图。回答页码指 PDF 页序，请核对原文。")

        if self.summary:
            self.note.setText(f"模型：{settings.model} · 服务：{urlsplit(settings.base_url).hostname}\n"
                              "使用整篇论文原文和你填写的个人背景，可能产生 API 费用。\n"
                              "只分析可提取文字，引用使用 PDF 页序；生成时可继续操作首页。")

    def choose_attachments(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择问答附件", "", "支持的附件 (*.pdf *.txt *.md *.csv *.png *.jpg *.jpeg)")
        if not paths:
            return
        try:
            self.attachments = validate_paths((*self.attachments, *paths))
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else "附件无法读取。")
            return
        self.refresh_attachments()

    def refresh_attachments(self):
        self.attachment_list.clear()
        self.attachment_list.addItems([f"附件{i} · {Path(p).name}" for i, p in enumerate(self.attachments, 1)])

    def remove_attachments(self):
        selected = {self.attachment_list.row(item) for item in self.attachment_list.selectedItems()}
        self.attachments = tuple(p for i, p in enumerate(self.attachments) if i not in selected)
        self.refresh_attachments()

    def render_history(self):
        self.transcript.setPlainText("\n\n".join(
            ("你：\n" if m["role"] == "user" else "AI：\n") + m["content"] for m in self.history))
        if self.summary:
            self.transcript.setPlainText(next((m["content"] for m in reversed(self.history) if m["role"] == "assistant"), ""))
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def update_scope(self, *_):
        self.page.setEnabled(self.scope.currentIndex() == 1 and self.task is None)
        try:
            text = paper_context(self.paper, self.page.value() - 1 if self.scope.currentIndex() else None)
            self.context_label.setText(f"约 {len(text):,} 字符原文")
        except ValueError as exc:
            self.context_label.setText(str(exc))

    def submit(self):
        if self.task is not None:
            return
        question = self.question.toPlainText().strip()
        if self.summary:
            if len(question) > 2000:
                self.status.setText("个人背景请控制在2000字以内。")
                return
            question = SUMMARY_PROMPT + (question or "未提供")
        if not question or len(question) > 4000:
            self.status.setText("请输入 1–4000 字的问题。")
            return
        page = self.page.value() - 1 if self.scope.currentIndex() else None
        try:
            paper_context(self.paper, page)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.pending_question = question
        self.partial_answer = ""
        self.request_status = "正在发送论文"
        self.render_history()
        streaming = self.streaming.isChecked()
        request_history = [] if self.summary else list(self.history)
        request_attachments = tuple(self.attachments)
        request_settings = replace(self.settings, timeout=self.timeout.value())
        self.task = Task(lambda t: asyncio.run(ask_paper(
            self.paper, request_settings, question, request_history, page, t.stop,
            on_status=t.status.emit, on_chunk=t.chunk.emit, stream=streaming, attachments=request_attachments)), self)
        self.task.status.connect(self.set_request_status)
        self.task.chunk.connect(self.receive_chunk)
        self.task.result.connect(self.answered)
        self.task.failed.connect(self.failed)
        self.task.finished.connect(self._task_finished)
        self.task.finished.connect(self.task.deleteLater)
        for control in (self.send, self.question, self.scope, self.page, self.clear, self.timeout, self.streaming, self.add_attachment, self.remove_attachment, self.attachment_list):
            control.setEnabled(False)
        self.stop.setEnabled(True)
        self.started_at = time.monotonic()
        self.status.setText("正在发送论文并等待模型回答… 可随时停止。")
        self.wait_timer.start()
        self.task.start()

    def update_wait_status(self):
        if self.task is not None and not self.task.stop.is_set():
            elapsed = int(time.monotonic() - self.started_at)
            self.status.setText(f"已等待 {elapsed} 秒 · {self.request_status}，可点击停止。")

    def set_request_status(self, status):
        self.request_status = status
        self.update_wait_status()

    def receive_chunk(self, text):
        if not self.partial_answer:
            if self.summary:
                self.transcript.clear()
                self.transcript.appendPlainText("论文总结（接收中，尚未完成）：\n")
            else:
                self.transcript.appendPlainText("\n你：\n" + self.pending_question + "\n\nAI（接收中，尚未完成）：\n")
        self.partial_answer += text
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def answered(self, answer):
        self.wait_timer.stop()
        self.partial_answer = ""
        if self.summary:
            self.history.clear()
        self.history.extend([{"role": "user", "content": self.pending_question},
                             {"role": "assistant", "content": answer}])
        self.render_history()
        if not self.summary:
            self.question.clear()
        if "【回答被接口截断" in answer:
            self.status.setText("回答不完整：接口达到输出上限。可缩小问题范围或在高级参数中提高输出上限。")
        else:
            self.status.setText("回答完成。引用页码由模型生成，请结合原文核对。")

    def failed(self, kind, message):
        self.wait_timer.stop()
        self.status.setText("已停止问答。" if kind == "Cancelled" else message)
        if self.partial_answer:
            self.transcript.appendPlainText("\n\n【回答未完成：可复制已接收文字，但不会加入后续问答上下文。】")

    def _task_finished(self):
        self.wait_timer.stop()
        self.task = None
        for control in (self.send, self.question, self.scope, self.clear, self.timeout, self.streaming, self.add_attachment, self.remove_attachment, self.attachment_list):
            control.setEnabled(True)
        self.stop.setEnabled(False)
        self.update_scope()
        if self.close_when_stopped:
            super().reject()

    def cancel(self):
        if self.task is not None:
            self.task.stop.set()
            self.stop.setEnabled(False)
            self.status.setText("正在停止问答…")

    def reject(self):
        if self.task is not None:
            self.close_when_stopped = True
            self.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self.task is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)

    def copy_answer(self):
        if self.partial_answer:
            QApplication.clipboard().setText("【回答未完成】\n" + self.partial_answer)
            self.status.setText("已复制当前不完整回答。")
            return
        for message in reversed(self.history):
            if message["role"] == "assistant":
                QApplication.clipboard().setText(message["content"])
                self.status.setText("最近回答已复制。")
                break

    def clear_history(self):
        self.partial_answer = ""
        self.history.clear()
        self.render_history()
        self.status.setText("对话已清空。")
