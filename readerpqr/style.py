STYLE = """
QMainWindow, QDialog { background: #f4f6f8; }
QWidget { color: #20303c; font-family: 'Microsoft YaHei UI', 'Noto Sans CJK SC', sans-serif; font-size: 13px; }
QFrame#sidebar { background: #152d39; border: none; }
QFrame#sidebar QLabel { color: #c1d2d9; }
QLabel#brand { color: #ffffff; font-size: 26px; font-weight: 700; }
QLabel#eyebrow { color: #83a2b0; font-size: 11px; }
QLabel#title { font-size: 19px; font-weight: 650; }
QLabel#muted { color: #6f818c; }
QLabel#notice { padding: 10px 14px; background: #e6f2ef; color: #285e56; border-radius: 7px; }
QPushButton, QToolButton { background: #ffffff; border: 1px solid #d4dfe4; border-radius: 6px; padding: 7px 12px; }
QPushButton:hover, QToolButton:hover { background: #eaf3f2; border-color: #71a49b; }
QPushButton:disabled, QToolButton:disabled { color: #96a3a9; background: #ecf0f2; }
QPushButton#primary { color: #ffffff; background: #177c6b; border: 1px solid #177c6b; font-weight: 600; }
QPushButton#primary:hover { background: #126453; }
QPushButton#primary:disabled { background: #9dbdb6; border-color: #9dbdb6; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: white; padding: 6px 8px; border: 1px solid #d4dfe4; border-radius: 5px; selection-background-color: #bcdfd5; }
QListWidget { border: none; background: #152d39; color: #c1d2d9; outline: none; }
QListWidget::item { padding: 12px 8px; border-radius: 5px; margin: 2px 0; }
QListWidget::item:selected { color: white; background: #28535e; }
QListWidget::item:hover { background: #214450; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 10px 18px; background: transparent; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #176b5d; border-bottom: 2px solid #177c6b; font-weight: 600; }
QScrollArea { border: none; background: #eef2f5; }
QFrame#row { background: #ffffff; border: 1px solid #dbe4e8; border-radius: 8px; }
QFrame#translation { background: #ffffff; border: 1px solid #dbe4e8; border-radius: 7px; }
QLabel#translationText { font-size: 15px; }
QProgressBar { border: 0; border-radius: 3px; background: #dce5e8; height: 6px; color: transparent; }
QProgressBar::chunk { background: #238c78; border-radius: 3px; }
QScrollBar:vertical { background: #eaf0f3; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #bdcbd2; min-height: 30px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { color: #617582; background: #ffffff; }
"""
