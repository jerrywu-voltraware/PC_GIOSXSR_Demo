"""藍牙掃描頁 — 對照 Flutter device_ble_scan_screen.dart（簡化版，無背景圖）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QProgressBar, QMessageBox,
)
from qasync import asyncSlot

from ..ble_manager import BleManager
from ..constants import FILTER_NAME


class ScanPage(QWidget):
    device_connected = pyqtSignal(str, str)  # (address, name)

    def __init__(self, ble: BleManager, parent=None):
        super().__init__(parent)
        self.ble = ble
        self._results: list[tuple[str, str, int]] = []  # (address, name, rssi)
        self._filter_enabled = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("掃描 BLE 裝置")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        top.addWidget(title)
        top.addStretch(1)
        root.addLayout(top)

        # List
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.list_widget, 1)

        # Progress bar (掃描中)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # busy indicator
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # Buttons
        bottom = QHBoxLayout()
        self.scan_btn = QPushButton("開始掃描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.connect_btn = QPushButton("連線選取裝置")
        self.connect_btn.clicked.connect(self._on_connect_clicked)

        bottom.addStretch(1)
        bottom.addWidget(self.scan_btn)
        bottom.addWidget(self.connect_btn)
        root.addLayout(bottom)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555;")
        root.addWidget(self.status_label)

    def _on_filter_toggled(self, checked: bool) -> None:
        self._filter_enabled = checked
        self._render_list()

    def _render_list(self) -> None:
        self.list_widget.clear()
        for address, name, rssi in self._results:
            if self._filter_enabled and FILTER_NAME not in (name or ""):
                continue
            if not name or name == "Unknown Device":
                continue
            item = QListWidgetItem(f"[{rssi:>4} dBm]  {name}   ({address})")
            item.setData(Qt.ItemDataRole.UserRole, (address, name))
            self.list_widget.addItem(item)

    @asyncSlot()
    async def start_scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("掃描中 ...")
        self._results.clear()
        self.list_widget.clear()
        try:
            items = await BleManager.scan(timeout=3.0)
            for dev, adv in items:
                name = adv.local_name or dev.name or ""
                self._results.append((dev.address, name, adv.rssi or 0))
            self._render_list()
            self.status_label.setText(f"找到 {len(self._results)} 個裝置。雙擊或選取後按「連線」。")
        except Exception as e:
            QMessageBox.warning(self, "掃描失敗", f"無法掃描：{e}\n\n請確認藍牙已開啟。")
            self.status_label.setText("掃描失敗")
        finally:
            self.progress.setVisible(False)
            self.scan_btn.setEnabled(True)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._connect_to_item(item)

    def _on_connect_clicked(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "請先選取一個裝置")
            return
        self._connect_to_item(item)

    @asyncSlot()
    async def _connect_to_item(self, item: QListWidgetItem) -> None:
        address, name = item.data(Qt.ItemDataRole.UserRole)
        self.connect_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.status_label.setText(f"連線 {name} ...")
        try:
            await self.ble.connect(address)
            self.status_label.setText(f"已連線 {name}")
            self.device_connected.emit(address, name)
        except Exception as e:
            QMessageBox.warning(self, "連線失敗", f"連線失敗：{e}")
            self.status_label.setText("連線失敗")
        finally:
            self.connect_btn.setEnabled(True)
            self.scan_btn.setEnabled(True)
