from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from .models import Block
from .storage import Settings, endpoint_url, save_settings
from .translate import AITranslator
from .workers import Task


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 设置 · readerPQR")
        self.setMinimumWidth(650)
        self.settings = settings
        self.test_task = None
        root = QVBoxLayout(self)
        note = QLabel("PDF 在本地解析。翻译时，仅将选定段落文字和术语表发送到你配置的 API。\nAPI 服务可能计费；请使用你有权发送的文献。")
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        root.addLayout(form)
        preset = QComboBox()
        preset.addItems(["保留当前配置", "智谱 GLM", "通用 Chat Completions（自行填写）", "本机服务（自行填写模型）"])
        preset_row = QHBoxLayout()
        preset_row.addWidget(preset, 1)
        apply_preset = QPushButton("应用预设")
        apply_preset.setAutoDefault(False)
        preset_row.addWidget(apply_preset)
        form.addRow("服务预设", preset_row)
        self.url = QLineEdit(settings.base_url)
        self.model = QLineEdit(settings.model)
        self.key = QLineEdit(settings.api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API Key（本机无鉴权服务可留空）")
        form.addRow("API Base URL", self.url)
        form.addRow("模型名称", self.model)
        form.addRow("API Key", self.key)
        self.remember = QCheckBox("用 Windows DPAPI 加密保存密钥（绑定当前 Windows 用户）")
        self.remember.setChecked(settings.remember_key and sys.platform == "win32")
        self.remember.setEnabled(sys.platform == "win32")
        form.addRow("", self.remember)
        self.auto = QCheckBox("导入 PDF 后自动翻译全文（可能产生 API 费用）")
        self.auto.setChecked(settings.auto_translate)
        form.addRow("自动翻译", self.auto)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setValue(settings.timeout)
        self.timeout.setSuffix(" 秒")
        self.batch = QSpinBox()
        self.batch.setRange(500, 12000)
        self.batch.setSingleStep(500)
        self.batch.setValue(settings.batch_chars)
        form.addRow("请求超时", self.timeout)
        form.addRow("每批文字上限", self.batch)
        self.glossary = QPlainTextEdit(settings.glossary)
        self.glossary.setMaximumHeight(105)
        self.glossary.setPlaceholderText("每行一条，例如：action chunk=动作块")
        form.addRow("学术术语表", self.glossary)
        self.extra = QPlainTextEdit(settings.extra_json)
        self.extra.setMaximumHeight(65)
        self.extra.setPlaceholderText("{}")
        form.addRow("高级 JSON 参数", self.extra)
        self.consent = QCheckBox("我确认当前地址可信，允许将文献文字发送至该 API")
        self.consent.setChecked(settings.consent_endpoint == endpoint_url(settings.base_url))
        root.addWidget(self.consent)
        self.url.textChanged.connect(lambda: self.consent.setChecked(False))
        apply_preset.clicked.connect(lambda: self._preset(preset.currentIndex()))
        footer = QHBoxLayout()
        self.test = QPushButton("测试连接")
        self.test.clicked.connect(self.test_connection)
        footer.addWidget(self.test)
        self.result_label = QLabel("测试只发送一句示例文字，不发送你的 PDF。")
        self.result_label.setWordWrap(True)
        footer.addWidget(self.result_label, 1)
        root.addLayout(footer)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def _preset(self, index):
        if index == 1:
            self.url.setText("https://open.bigmodel.cn/api/paas/v4")
            self.model.setText("glm-4.7-flash")
            self.extra.setPlainText('{"thinking":{"type":"disabled"}}')
        elif index == 2:
            self.url.clear()
            self.url.setPlaceholderText("https://你的服务地址/v1")
            self.model.clear()
            self.extra.setPlainText("{}")
        elif index == 3:
            self.url.setText("http://127.0.0.1:11434/v1")
            self.model.clear()
            self.extra.setPlainText("{}")
        if index:
            self.key.clear()  # Never reuse an API credential on another provider silently.
            self.consent.setChecked(False)

    def collect(self):
        value = replace(self.settings, base_url=self.url.text().strip(),
                        model=self.model.text().strip(), api_key=self.key.text().strip(),
                        remember_key=self.remember.isChecked(), auto_translate=self.auto.isChecked(),
                        timeout=self.timeout.value(), batch_chars=self.batch.value(),
                        glossary=self.glossary.toPlainText(), extra_json=self.extra.toPlainText())
        value.validate()
        value.consent_endpoint = endpoint_url(value.base_url) if self.consent.isChecked() else ""
        return value

    def save(self):
        try:
            value = self.collect()
            save_settings(value)
        except Exception as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self.settings = value
        self.accept()

    def test_connection(self):
        try:
            value = self.collect()
        except ValueError as exc:
            QMessageBox.warning(self, "配置有误", str(exc))
            return

        async def check(task):
            client = AITranslator(value, task.stop)
            try:
                return await client.translate([Block("test", 0, (0, 0, 10, 10), "This is a connection test.")])
            finally:
                await client.close()

        task = Task(lambda t: asyncio.run(check(t)), self)
        self.test_task = task
        self.test.setEnabled(False)
        self.buttons.setEnabled(False)
        self.result_label.setText("正在验证接口与翻译格式…")
        task.result.connect(lambda _: self.result_label.setText("连接成功，返回格式有效。"))
        task.failed.connect(lambda _, message: self.result_label.setText(message))
        task.finished.connect(self._test_finished)
        task.finished.connect(task.deleteLater)
        task.start()

    def _test_finished(self):
        self.test_task = None
        self.test.setEnabled(True)
        self.buttons.setEnabled(True)

    def reject(self):
        if self.test_task is not None:
            self.test_task.stop.set()
            self.result_label.setText("正在停止连接测试，请在停止后关闭。")
            return
        super().reject()
