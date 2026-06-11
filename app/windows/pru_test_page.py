"""PRU 測試頁 — 對照 Flutter device_pru_test_screen.dart + pru_static/dynamic_info_card.dart。

布局：
 ┌─────────────────────────────────────────────┐
 │ [← 返回]           [重連狀態 banner]          │
 ├─────────────────────────────────────────────┤
 │ PTU Static Param [dropdown] [發送]           │
 │ PRU Control      [dropdown] [發送]           │
 ├─────────────────────────────────────────────┤
 │ PRU Static Info  [刷新]                      │
 │   (20B 解析欄位)                              │
 ├─────────────────────────────────────────────┤
 │ PRU Dynamic Info [刷新] [自動刷新 ▶/⏸]       │
 │   Validity 表格                               │
 │   (8 個量測欄位)                              │
 │   PRU Alert 表格                              │
 │   Tester Command                              │
 └─────────────────────────────────────────────┘
"""
from __future__ import annotations

import time
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QScrollArea, QMessageBox,
)
from qasync import asyncSlot

from ..ble_manager import BleManager
from ..constants import (
    PACKET_STATIC_PARAMETER, PACKET_CONTROL,
    UUID_PTU_STATIC_PARAM, UUID_PRU_CONTROL,
    UUID_PRU_STATIC_READ, UUID_PRU_DYNAMIC_READ,
    UUID_PRU_NOTIFY,
    VALIDITY_BIT_LABELS, DYNAMIC_ALERT_BIT_LABELS,
)
from ..protocol import (
    parse_pru_static, parse_pru_dynamic,
    parse_alert_byte, format_mac_from_notify, get_bits_msb,
)


# -------------------------------------------------------------------
# PRU Static Info 卡
# -------------------------------------------------------------------
class PruStaticInfoCard(QGroupBox):
    def __init__(self, ble: BleManager, parent=None):
        super().__init__("PRU Static Info", parent)
        self.ble = ble
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        self.updated_label = QLabel("")
        self.updated_label.setStyleSheet("color: #555; font-size: 11px;")
        top.addStretch(1)
        top.addWidget(self.updated_label)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setColumnMinimumWidth(0, 340)
        self.grid.setColumnMinimumWidth(1, 600)
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setVerticalSpacing(6)
        root.addLayout(self.grid)

    def _clear_grid(self) -> None:
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _render(self, lines: list[tuple[str, str]]) -> None:
        from PyQt6.QtWidgets import QSizePolicy
        self._clear_grid()
        for row, (k, v) in enumerate(lines):
            key_lbl = QLabel(k)
            key_lbl.setStyleSheet("font-weight: bold;")
            key_lbl.setWordWrap(True)
            key_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            key_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            val_lbl = QLabel(v)
            val_lbl.setStyleSheet("color: #c00;")
            val_lbl.setWordWrap(False)
            val_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.grid.addWidget(key_lbl, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(val_lbl, row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    @asyncSlot()
    async def refresh(self) -> None:
        if not self.ble.is_connected:
            return
        try:
            data = await self.ble.read(UUID_PRU_STATIC_READ)
        except Exception as e:
            self._render([("讀取失敗", str(e))])
            return
        info = parse_pru_static(list(data))
        self._render(info.as_display_lines())
        self.updated_label.setText(f"更新時間: {datetime.now().strftime('%H:%M:%S')}")


# -------------------------------------------------------------------
# PRU Dynamic Info 卡
# -------------------------------------------------------------------
class PruDynamicInfoCard(QGroupBox):
    def __init__(self, ble: BleManager, parent=None):
        super().__init__("PRU Dynamic Info", parent)
        self.ble = ble
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(1000)
        self._auto_timer.timeout.connect(self._tick)
        self._build_ui()

    def _build_ui(self) -> None:
        from PyQt6.QtWidgets import QSizePolicy
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        self.auto_btn = QPushButton("▶ 自動刷新")
        self.auto_btn.setCheckable(True)
        self.auto_btn.toggled.connect(self._on_auto_toggled)
        self.updated_label = QLabel("")
        self.updated_label.setStyleSheet("color: #555; font-size: 11px;")
        top.addStretch(1)
        top.addWidget(self.updated_label)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.auto_btn)
        root.addLayout(top)

        # 單一主 grid，col 0 = 標籤，col 1 = 值，寬度對齊 Static Info
        self.main_grid = QGridLayout()
        self.main_grid.setColumnMinimumWidth(0, 340)
        self.main_grid.setColumnMinimumWidth(1, 600)
        self.main_grid.setColumnStretch(0, 0)
        self.main_grid.setColumnStretch(1, 1)
        self.main_grid.setVerticalSpacing(6)
        root.addLayout(self.main_grid)

        self._main_row = 0  # 目前填到第幾行

    def _on_auto_toggled(self, checked: bool) -> None:
        if checked:
            self.auto_btn.setText("⏸ 停止自動")
            self._auto_timer.start()
        else:
            self.auto_btn.setText("▶ 自動刷新")
            self._auto_timer.stop()

    def stop_auto(self) -> None:
        if self.auto_btn.isChecked():
            self.auto_btn.setChecked(False)

    def _tick(self) -> None:
        if not self.ble.is_connected:
            self.stop_auto()
            return
        # refresh 是 asyncSlot，可直接呼叫
        self.refresh()

    def _clear_main_grid(self) -> None:
        while self.main_grid.count():
            it = self.main_grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._main_row = 0

    def _add_row(self, key: str, value: str, key_style: str = "", val_style: str = "color: #c00;") -> None:
        from PyQt6.QtWidgets import QSizePolicy
        key_lbl = QLabel(key)
        key_lbl.setStyleSheet(key_style or "font-weight: bold;")
        key_lbl.setWordWrap(True)
        key_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(val_style)
        val_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_grid.addWidget(key_lbl, self._main_row, 0,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.main_grid.addWidget(val_lbl, self._main_row, 1,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._main_row += 1

    def _add_bits_rows(self, bits: list[int], labels: list[str]) -> None:
        for label, bit in zip(labels, bits):
            key_lbl = QLabel(label)
            key_lbl.setStyleSheet("border: 1px solid #bbb; padding: 2px;")
            val_lbl = QLabel(str(bit))
            val_lbl.setStyleSheet("color: #c00; border: 1px solid #bbb; padding: 2px;")
            self.main_grid.addWidget(key_lbl, self._main_row, 0,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.main_grid.addWidget(val_lbl, self._main_row, 1,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._main_row += 1

    @asyncSlot()
    async def refresh(self) -> None:
        if not self.ble.is_connected:
            return
        try:
            data = await self.ble.read(UUID_PRU_DYNAMIC_READ)
        except Exception as e:
            self._clear_main_grid()
            self._add_row("讀取失敗", str(e))
            return

        info = parse_pru_dynamic(list(data))
        self._clear_main_grid()

        if info.valid:
            # --- optionalFieldsValidity ---
            self._add_row("- optionalFieldsValidity",
                          f"0x{info.optional_fields_validity:02X}")
            self._add_bits_rows(get_bits_msb(info.optional_fields_validity),
                                VALIDITY_BIT_LABELS)

        # --- 量測值 ---
        for k, v in info.as_display_lines():
            self._add_row(f"- {k}", v)

        if info.valid:
            # --- pruAlert ---
            self._add_row("- pruAlert", f"0x{info.pru_alert:02X}")
            self._add_bits_rows(get_bits_msb(info.pru_alert),
                                DYNAMIC_ALERT_BIT_LABELS)

            # --- Tester Command ---
            self._add_row("- Tester Command", f"0x{info.tester_cmd:02X}")

        self.updated_label.setText(f"更新時間: {datetime.now().strftime('%H:%M:%S')}")


# -------------------------------------------------------------------
# PRU Test Page
# -------------------------------------------------------------------
class PruTestPage(QWidget):
    back_requested = pyqtSignal()
    # 跨 thread 用：bleak notify callback 會在 asyncio thread 觸發，
    # 透過 signal 轉回 Qt UI thread。
    _notify_signal = pyqtSignal(bytes)

    def __init__(self, ble: BleManager, parent=None):
        super().__init__(parent)
        self.ble = ble
        self._last_alert_ts: float = 0.0  # 5 秒節流
        self._notify_enabled = False
        self._build_ui()
        self._notify_signal.connect(self._on_notify_ui)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 返回")
        self.back_btn.clicked.connect(self._on_back_clicked)
        self.status_banner = QLabel("")
        self.status_banner.setStyleSheet(
            "background-color: rgba(0,0,0,0.7); color: white; padding: 6px; border-radius: 6px;"
        )
        self.status_banner.setVisible(False)
        top.addWidget(self.back_btn)
        top.addWidget(self.status_banner, 1)
        outer.addLayout(top)

        # 內容放 scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        root = QVBoxLayout(content)

        # ------- PTU Static Parameter -------
        ptu_row = QHBoxLayout()
        ptu_row.addWidget(QLabel("PTU Static Parameter"))
        ptu_row.addStretch(1)
        self.ptu_combo = QComboBox()
        self.ptu_combo.addItems(list(PACKET_STATIC_PARAMETER.keys()))
        ptu_row.addWidget(self.ptu_combo)
        self.ptu_send_btn = QPushButton("發送")
        self.ptu_send_btn.clicked.connect(self._on_ptu_send)
        ptu_row.addWidget(self.ptu_send_btn)
        root.addLayout(ptu_row)

        # ------- PRU Control -------
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("PRU Control"))
        ctrl_row.addStretch(1)
        self.ctrl_combo = QComboBox()
        self.ctrl_combo.addItems(list(PACKET_CONTROL.keys()))
        ctrl_row.addWidget(self.ctrl_combo)
        self.ctrl_send_btn = QPushButton("發送")
        self.ctrl_send_btn.clicked.connect(self._on_ctrl_send)
        ctrl_row.addWidget(self.ctrl_send_btn)
        root.addLayout(ctrl_row)

        # ------- Info Cards -------
        self.static_card = PruStaticInfoCard(self.ble)
        root.addWidget(self.static_card)
        self.dynamic_card = PruDynamicInfoCard(self.ble)
        root.addWidget(self.dynamic_card)

        root.addStretch(1)

    # -------------- slots --------------
    @asyncSlot()
    async def _on_ptu_send(self) -> None:
        key = self.ptu_combo.currentText()
        bytes_ = PACKET_STATIC_PARAMETER.get(key)
        if not bytes_ or not self.ble.is_connected:
            return
        try:
            await self.ble.write(UUID_PTU_STATIC_PARAM, bytes_)
            self._flash_banner(f"✅ 已送出 PTU Static：{key}")
        except Exception as e:
            QMessageBox.warning(self, "發送失敗", str(e))

    @asyncSlot()
    async def _on_ctrl_send(self) -> None:
        key = self.ctrl_combo.currentText()
        bytes_ = PACKET_CONTROL.get(key)
        if not bytes_ or not self.ble.is_connected:
            return
        try:
            await self.ble.write(UUID_PRU_CONTROL, bytes_)
            self._flash_banner(f"✅ 已送出 PRU Control：{key}")
        except Exception as e:
            QMessageBox.warning(self, "發送失敗", str(e))

    def _on_back_clicked(self) -> None:
        self.dynamic_card.stop_auto()
        self.back_requested.emit()

    # -------------- notify 整合 --------------
    @asyncSlot()
    async def enter_page(self) -> None:
        """由外部於顯示頁面時呼叫：啟用 notify + 首次 refresh。"""
        if not self.ble.is_connected:
            return
        # 註冊 notify callback（同步，不 await）
        self.ble.set_notification_callback(self._on_notify_thread)
        if not self._notify_enabled:
            try:
                await self.ble.enable_notify(UUID_PRU_NOTIFY)
                self._notify_enabled = True
            except Exception as e:
                print(f"enable_notify 失敗: {e}")
        # 首次載入 static / dynamic
        await self.static_card.refresh()
        await self.dynamic_card.refresh()

    def leave_page(self) -> None:
        self.dynamic_card.stop_auto()

    def _on_notify_thread(self, uuid: str, value: bytearray) -> None:
        """從 bleak asyncio thread 呼叫，必須 emit signal 轉回 UI thread。"""
        try:
            self._notify_signal.emit(bytes(value))
        except Exception as e:
            print(f"notify emit 失敗: {e}")

    @pyqtSlot(bytes)
    def _on_notify_ui(self, data: bytes) -> None:
        if not data:
            return
        # 5 秒節流
        now = time.time()
        if now - self._last_alert_ts < 5.0:
            return
        self._last_alert_ts = now

        value = list(data)
        alert_byte = value[0]
        decoded = parse_alert_byte(alert_byte)
        address = format_mac_from_notify(value)
        msg = (
            f"Alert Byte: 0x{alert_byte:02X}\n"
            f"Address: {address}\n\n"
            + ("\n".join(decoded) if decoded else "⚪ 無警報")
        )
        box = QMessageBox(self)
        box.setWindowTitle("PRU Alert Notification")
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Close)
        box.exec()

    # -------------- 狀態 banner --------------
    def set_reconnect_status(self, text: str) -> None:
        if text:
            self.status_banner.setText(text)
            self.status_banner.setVisible(True)
        else:
            self.status_banner.setVisible(False)

    def _flash_banner(self, text: str, ms: int = 1500) -> None:
        self.status_banner.setText(text)
        self.status_banner.setVisible(True)
        QTimer.singleShot(ms, lambda: self.status_banner.setVisible(False))
