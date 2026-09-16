"""An optional, local-only author support page."""
from pathlib import Path
import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


def payment_image():
    return Path(__file__).resolve().parent / "assets" / "wechat-tip.jpg"


class SupportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("支持作者 · 自愿打赏")
        self.resize(500, 760)
        if self.screen():
            self.resize(500, min(760, int(self.screen().availableGeometry().height() * 0.85)))
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("supportBody")
        body.setStyleSheet("QWidget#supportBody { background: #ffffff; } QLabel { color: #1c2935; background: transparent; }")
        content = QVBoxLayout(body)
        title = QLabel("感谢支持 readerPQR")
        title.setStyleSheet("font-size:22px;font-weight:600;color:#147d70;padding:8px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)
        for text in (
            "制作人：彭先生\npengqianrang2026@ia.ac.cn",
            "如果这个工具帮助了你的论文阅读，欢迎自愿打赏支持维护。\n不打赏也能正常使用全部功能。",
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content.addWidget(label)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(payment_image()))
        if pixmap.isNull():
            self.qr.setText("收款码图片未找到，请从项目 README 查看。")
        else:
            self.qr.setPixmap(pixmap.scaledToWidth(320, Qt.TransformationMode.SmoothTransformation))
        content.addWidget(self.qr)
        note = QLabel("请用手机微信扫码，付款前核对收款人与实际金额。\n图片标注金额为 ¥0.50。\n\n打赏不包含模型 API 额度或额外服务承诺。\n也欢迎通过 Star、反馈问题或贡献代码支持项目。")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(note)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存收款码图片")
        self.save_button.setEnabled(not pixmap.isNull())
        self.save_button.clicked.connect(self.save_image)
        buttons.addWidget(self.save_button)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def save_image(self):
        destination, _ = QFileDialog.getSaveFileName(self, "保存微信收款码", "readerPQR-微信打赏.jpg", "JPEG 图片 (*.jpg)")
        if not destination:
            return
        if not destination.lower().endswith((".jpg", ".jpeg")):
            destination += ".jpg"
        try:
            if Path(destination).resolve() != payment_image().resolve():
                shutil.copyfile(payment_image(), destination)
        except OSError:
            QMessageBox.warning(self, "保存失败", "无法保存图片，请检查文件夹权限或选择其他位置。")
            return
        QMessageBox.information(self, "图片已保存", "收款码原图已保存。付款前请核对收款人和实际金额。")
