"""Shared desktop typography and teal controls."""
import os
from pathlib import Path
from PyQt6.QtGui import QFont, QFontDatabase


def apply_theme(app):
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msjh.ttc"
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    app.setStyleSheet("""
        QWidget { color: #183d40; }
        QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #edf5f5; }
        QGroupBox { background: white; border: 1px solid #c5dada; border-radius: 8px;
                    margin-top: 16px; padding: 12px; font-weight: bold; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
        QPushButton { padding: 7px 12px; background: #e0eeee; border: 1px solid #9ebfbe; border-radius: 5px; }
        QPushButton:hover { background: #c8e3e0; }
        QPushButton:checked { background: #116360; color: white; }
        QPushButton:disabled { color: #879697; background: #eef0f0; border-color: #d5dada; }
        QComboBox { padding: 5px; min-height: 22px; }
        QTreeWidget, QPlainTextEdit, QListWidget { background: white; border: 1px solid #d2e0e0; }
        QHeaderView::section { background: #e0eeee; padding: 5px; border: none; }
    """)
