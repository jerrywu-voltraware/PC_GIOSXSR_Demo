"""設備資訊頁 — 對照 Flutter device_info_screen.dart。列出所有 service + characteristic。"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QMessageBox,
)
from qasync import asyncSlot

from ..ble_manager import BleManager


def _props_to_string(c) -> str:
    """BleakGATTCharacteristic.properties → 可讀字串。"""
    mapping = {
        "read": "Read",
        "write": "Write",
        "write-without-response": "WriteWithoutResp",
        "notify": "Notify",
        "indicate": "Indicate",
    }
    return ", ".join(mapping.get(p, p) for p in c.properties)


class InfoPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, ble: BleManager, parent=None):
        super().__init__(parent)
        self.ble = ble
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 返回")
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.refresh_btn = QPushButton("重新載入")
        self.refresh_btn.clicked.connect(self.load_services)
        self.status_label = QLabel("")
        top.addWidget(self.back_btn)
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        top.addWidget(self.status_label)
        root.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["UUID", "Properties"])
        self.tree.setColumnWidth(0, 420)
        root.addWidget(self.tree, 1)

    @asyncSlot()
    async def load_services(self) -> None:
        self.tree.clear()
        if not self.ble.is_connected:
            self.status_label.setText("未連線")
            return
        self.status_label.setText("載入中 ...")
        try:
            # bleak 連線時會自動 discover，這裡只重新讀取列表
            services = self.ble.services()
            for svc in services:
                svc_item = QTreeWidgetItem([f"Service: {svc.uuid}", ""])
                for c in svc.characteristics:
                    ch_item = QTreeWidgetItem([
                        f"Characteristic: {c.uuid}",
                        _props_to_string(c),
                    ])
                    svc_item.addChild(ch_item)
                self.tree.addTopLevelItem(svc_item)
                svc_item.setExpanded(True)
            self.status_label.setText(f"共 {len(services)} 個 service")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"載入 services 失敗：{e}")
            self.status_label.setText("載入失敗")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 每次進頁面自動載入
        self.load_services()
