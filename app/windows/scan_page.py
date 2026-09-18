"""藍牙掃描頁 — 對照 Flutter device_ble_scan_screen.dart（簡化版，無背景圖）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QProgressBar, QMessageBox,
)
from qasync import asyncSlot

from ..ble_manager import BleManager
from ..diagnostics import diagnostics_log_path, write_diagnostic


class ScanPage(QWidget):
    device_connected = pyqtSignal(str, str)  # (address, name)

    def __init__(self, ble: BleManager, parent=None):
        super().__init__(parent)
        self.ble = ble
        self._results: list[tuple[str, str, int]] = []  # (address, name, rssi)
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
        self.disconnect_btn = QPushButton("斷線選取裝置")
        self.disconnect_btn.clicked.connect(self._disconnect_selected)

        bottom.addStretch(1)
        bottom.addWidget(self.scan_btn)
        bottom.addWidget(self.connect_btn)
        bottom.addWidget(self.disconnect_btn)
        root.addLayout(bottom)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555;")
        root.addWidget(self.status_label)

    def _render_list(self) -> None:
        self.list_widget.clear()
        connected = dict(self.ble.connected_devices())
        items = [(address, name, 0) for address, name in connected.items()]
        items += [item for item in self._results if item[0] not in connected]
        for address, name, rssi in items:
            if not name or name in ("Unknown Device", "(Unknown)"):
                continue
            display_name = name or "(Unknown)"
            prefix = "已連線" if address in connected else f"{rssi:>4} dBm"
            item = QListWidgetItem(f"[{prefix}]  {display_name}   ({address})")
            item.setData(Qt.ItemDataRole.UserRole, (address, name))
            self.list_widget.addItem(item)

    def showEvent(self, event):
        super().showEvent(event)
        self._render_list()

    @asyncSlot()
    async def _disconnect_selected(self):
        item = self.list_widget.currentItem()
        if not item or not self.connect_btn.isEnabled():
            return
        address, name = item.data(Qt.ItemDataRole.UserRole)
        if address not in dict(self.ble.connected_devices()):
            return
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        try:
            await self.ble.connect(address)
            await self.ble.disconnect()
            self._render_list()
        finally:
            self.disconnect_btn.setEnabled(True)
            self.connect_btn.setEnabled(True)

    @asyncSlot()
    async def start_scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("掃描中 ...")
        self._results.clear()
        self.list_widget.clear()
        try:
            items = await BleManager.scan(timeout=2.0)
            for dev, adv in items:
                name = adv.local_name or dev.name or "(Unknown)"
                self._results.append((dev.address, name, adv.rssi or 0))
            self._render_list()
            write_diagnostic(
                f"BLE scan UI: raw_count={len(self._results)} "
                f"visible_count={self.list_widget.count()} log={diagnostics_log_path()}"
            )
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
        if not self.connect_btn.isEnabled():
            return
        address, name = item.data(Qt.ItemDataRole.UserRole)
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.status_label.setText(f"連線 {name} ...")
        try:
            await self.ble.connect(address)
            self.ble.device_names[address] = name
            self.status_label.setText(f"已連線 {name}")
            self.device_connected.emit(address, name)
        except Exception as e:
            QMessageBox.warning(self, "連線失敗", f"連線失敗：{e}")
            self.status_label.setText("連線失敗")
        finally:
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(True)
            self.scan_btn.setEnabled(True)
