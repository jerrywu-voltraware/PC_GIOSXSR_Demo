"""MainWindow — 左右分割：左側 BLE 操作流程，右側 DAC 工具可收折（抽屜式）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QMessageBox, QHBoxLayout, QWidget, QPushButton
from qasync import asyncSlot

from ..ble_manager import BleManager
from ..updater import UpdateController
from ..version import APP_VERSION
from .scan_page import ScanPage
from .menu_page import MenuPage
from .info_page import InfoPage
from .pru_test_page import PruTestPage
from .dac_tool_page import DacToolPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GIOS BLE SR PC Demo v{APP_VERSION}")
        self.resize(700, 750)

        self.ble = BleManager()
        self.ble.set_disconnected_callback(self._on_ble_disconnected)
        self.update_controller = UpdateController(self)
        self._build_app_menu()

        # ── 左側：BLE 頁面堆疊 ──
        self.stack = QStackedWidget()

        self.scan_page = ScanPage(self.ble)
        self.menu_page = MenuPage()
        self.info_page = InfoPage(self.ble)
        self.pru_page = PruTestPage(self.ble)

        self.stack.addWidget(self.scan_page)   # index 0
        self.stack.addWidget(self.menu_page)   # index 1
        self.stack.addWidget(self.info_page)   # index 2
        self.stack.addWidget(self.pru_page)    # index 3

        # ── 右側：DAC 工具（抽屜式，預設收起）──
        self.dac_page = DacToolPage()
        self.dac_page.auto_load()
        self.dac_page.setVisible(False)       # 預設收起
        self._dac_open = False

        # ── 切換按鈕（垂直窄條，常駐於左右面板之間）──
        self.dac_toggle_btn = QPushButton("▶")
        self.dac_toggle_btn.setFixedWidth(22)
        self.dac_toggle_btn.setToolTip("展開 / 收起 DAC 工具面板")
        self.dac_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dac_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #dce8f8;
                border: none;
                border-left: 1px solid #b0c4de;
                font-size: 13px;
                color: #1a73e8;
            }
            QPushButton:hover { background: #b8d0f0; }
        """)
        self.dac_toggle_btn.clicked.connect(self._toggle_dac)

        # ── 中央佈局 ──
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self.stack, 1)
        h.addWidget(self.dac_toggle_btn)
        h.addWidget(self.dac_page)
        self.setCentralWidget(central)

        # Signals
        self.scan_page.device_connected.connect(self._on_connected)
        self.menu_page.open_info.connect(self._open_info)
        self.menu_page.open_pru_test.connect(self._open_pru)
        self.menu_page.disconnect_requested.connect(self._disconnect_and_back)
        self.info_page.back_requested.connect(self._back_to_menu)
        self.pru_page.back_requested.connect(self._back_to_menu)

        self.stack.setCurrentWidget(self.scan_page)
        QTimer.singleShot(1500, self.update_controller.check_for_updates)

    def _build_app_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        check_update_action = QAction("Check for updates", self)
        check_update_action.triggered.connect(
            lambda _checked=False: self.update_controller.check_for_updates(manual=True)
        )
        help_menu.addAction(check_update_action)

    # ------------- DAC 抽屜切換 -------------
    def _toggle_dac(self) -> None:
        self._dac_open = not self._dac_open
        self.dac_page.setVisible(self._dac_open)
        self.dac_toggle_btn.setText("◀" if self._dac_open else "▶")
        if self._dac_open:
            self.resize(1400, self.height())
        else:
            self.resize(700, self.height())

    # ------------- 頁面切換 -------------
    def _on_connected(self, address: str, name: str) -> None:
        self.menu_page.set_device_name(f"{name} ({address})")
        self.stack.setCurrentWidget(self.menu_page)

    def _open_info(self) -> None:
        self.stack.setCurrentWidget(self.info_page)

    def _open_pru(self) -> None:
        self.stack.setCurrentWidget(self.pru_page)
        # 啟動 notify + 首次 refresh
        self.pru_page.enter_page()

    def _back_to_menu(self) -> None:
        self.pru_page.leave_page()
        self.stack.setCurrentWidget(self.menu_page)

    @asyncSlot()
    async def _disconnect_and_back(self) -> None:
        self.pru_page.leave_page()
        try:
            await self.ble.disable_all_notify()
        except Exception:
            pass
        try:
            await self.ble.disconnect()
        except Exception:
            pass
        self.stack.setCurrentWidget(self.scan_page)

    # ------------- 斷線處理 -------------
    def _on_ble_disconnected(self) -> None:
        """bleak 從 asyncio thread 呼叫。用 singleShot 轉回 UI thread。"""
        QTimer.singleShot(0, self._show_disconnect_ui)

    def _show_disconnect_ui(self) -> None:
        self.pru_page.set_reconnect_status("⚠️ 已斷線，請重新掃描連線")
        # 自動退回掃描頁
        if self.stack.currentWidget() is not self.scan_page:
            self.stack.setCurrentWidget(self.scan_page)
            QMessageBox.information(self, "斷線", "裝置已斷線，請重新掃描並連線。")
        self.pru_page.set_reconnect_status("")

    # ------------- 關閉 -------------
    def closeEvent(self, event) -> None:
        # 清理 DAC serial 連線
        self.dac_page.cleanup()
        # 盡力同步清理 BLE
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.ble.disconnect())
        except Exception:
            pass
        super().closeEvent(event)
