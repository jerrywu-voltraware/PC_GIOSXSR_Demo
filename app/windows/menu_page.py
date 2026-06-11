"""主選單頁 — 只保留「設備資訊」、「PRU 測試」兩顆按鈕。"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel


class MenuPage(QWidget):
    open_info = pyqtSignal()
    open_pru_test = pyqtSignal()
    disconnect_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_name = ""
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 斷線並返回")
        self.back_btn.clicked.connect(self.disconnect_requested.emit)
        self.device_label = QLabel("")
        self.device_label.setStyleSheet("font-weight: bold;")
        top.addWidget(self.back_btn)
        top.addStretch(1)
        top.addWidget(self.device_label)
        root.addLayout(top)

        root.addStretch(1)

        btn_style = (
            "QPushButton { font-size: 22px; font-weight: bold; padding: 18px; "
            "background-color: #116360; color: white; border-radius: 8px; }"
            "QPushButton:hover { background-color: #178380; }"
        )

        self.info_btn = QPushButton("設備資訊")
        self.info_btn.setStyleSheet(btn_style)
        self.info_btn.setMinimumHeight(80)
        self.info_btn.clicked.connect(self.open_info.emit)

        self.pru_btn = QPushButton("PRU 測試")
        self.pru_btn.setStyleSheet(btn_style)
        self.pru_btn.setMinimumHeight(80)
        self.pru_btn.clicked.connect(self.open_pru_test.emit)

        row = QVBoxLayout()
        row.setSpacing(24)
        row.addWidget(self.info_btn)
        row.addWidget(self.pru_btn)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        inner = QVBoxLayout()
        inner.addLayout(row)
        container = QWidget()
        container.setLayout(inner)
        container.setMinimumWidth(400)
        wrap.addWidget(container, 3)
        wrap.addStretch(1)
        root.addLayout(wrap)

        root.addStretch(2)

    def set_device_name(self, name: str) -> None:
        self._device_name = name
        self.device_label.setText(f"已連線：{name}")
