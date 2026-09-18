"""Desktop routes matching the mobile app; no DAC tool."""
from __future__ import annotations
import asyncio
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from qasync import asyncSlot
from ..ble_manager import BleManager
from ..constants import UUID_PRU_CONTROL
from ..updater import UpdateController
from ..version import APP_VERSION
from .scan_page import ScanPage
from .menu_page import MenuPage
from .info_page import InfoPage
from .pru_test_page import PruTestPage
from .ota_page import OtaPage


class MainWindow(QMainWindow):
    disconnected = pyqtSignal()

    def __init__(self, check_updates=True):
        super().__init__()
        icon = QIcon(str(Path(__file__).resolve().parents[2] / "1024.png"))
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        self.setWindowTitle(f"GIOS BLE SR PC Demo v{APP_VERSION}")
        self.resize(960, 850)
        self.ble = BleManager()
        self.ble.set_disconnected_callback(self.disconnected.emit)
        self.disconnected.connect(self._show_disconnect_ui)
        self._closing = False
        self._closed = False
        self._starting_ota = False
        self._disconnect_cleanup = None
        self.update_controller = UpdateController(self)
        action = QAction("Check for updates", self)
        action.triggered.connect(lambda: self.update_controller.check_for_updates(manual=True))
        self.menuBar().addMenu("Help").addAction(action)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.scan_page = ScanPage(self.ble)
        self.menu_page = MenuPage()
        self.info_page = InfoPage(self.ble)
        self.pru_page = PruTestPage(self.ble)
        self.ota_page = OtaPage(self.ble)
        for page in (self.scan_page, self.menu_page, self.info_page, self.pru_page, self.ota_page):
            self.stack.addWidget(page)
        self.scan_page.device_connected.connect(self._on_connected)
        self.menu_page.open_info.connect(self._open_info)
        self.menu_page.open_pru_test.connect(self._open_pru)
        self.menu_page.open_ota.connect(self._start_ota)
        self.menu_page.disconnect_requested.connect(self._back_to_scan)
        self.info_page.back_requested.connect(self._back_to_menu)
        self.pru_page.back_requested.connect(self._back_to_menu)
        self.ota_page.back_requested.connect(self._disconnect_and_back)
        QApplication.instance().applicationStateChanged.connect(self._application_state)
        if check_updates:
            QTimer.singleShot(1500, self.update_controller.check_for_updates)

    def _application_state(self, state):
        if self.pru_page.controller:
            # Desktop inactive includes dialogs; only minimization/hidden pauses.
            self.pru_page.controller.set_foreground(not self.isMinimized() and self.isVisible())

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "pru_page"):
            self._application_state(None)

    def _on_connected(self, address, name):
        self.menu_page.set_device_name(f"{name} ({address})")
        if name == "OTAServiceMgr":
            self.stack.setCurrentWidget(self.ota_page)
            self.ota_page.enter_page()
        else:
            self.stack.setCurrentWidget(self.menu_page)

    def _open_info(self):
        self.stack.setCurrentWidget(self.info_page)

    def _open_pru(self):
        self.stack.setCurrentWidget(self.pru_page)
        self.pru_page.enter_page()

    @asyncSlot()
    async def _back_to_menu(self):
        task = self.pru_page.leave_page()
        if task:
            await task
        await self.info_page.leave_page()
        self.stack.setCurrentWidget(self.menu_page)

    @asyncSlot()
    async def _back_to_scan(self):
        task = self.pru_page.leave_page()
        if task:
            await task
        await self.info_page.leave_page()
        self.stack.setCurrentWidget(self.scan_page)

    @asyncSlot()
    async def _disconnect_and_back(self):
        task = self.pru_page.leave_page()
        if task:
            await task
        await self.info_page.leave_page()
        await self.ble.disable_all_notify()
        await self.ble.disconnect()
        self.stack.setCurrentWidget(self.scan_page)

    @asyncSlot()
    async def _start_ota(self):
        if self._starting_ota:
            return
        confirmed = QMessageBox.question(self, "確認更新", "這將會讓設備進入 OTA 更新模式並斷開目前的連線。確定要繼續嗎？")
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._starting_ota = True
        self.menu_page.setEnabled(False)
        try:
            # Start-OTA uses contains, unlike the PRU controller's endsWith.
            char = next((c for s in self.ble.services()
                         if any(suffix in str(s.uuid).lower() for suffix in ("fffe", "bbbb"))
                         for c in s.characteristics if str(c.uuid).lower() == UUID_PRU_CONTROL), None)
            if char is None:
                raise RuntimeError("找不到控制用的藍牙特徵值")
            await self.ble.write(char, [8, 0, 0, 0, 0], response=False)
            await asyncio.sleep(1)
            await self.ble.disconnect()
            self.stack.setCurrentWidget(self.scan_page)
        except Exception as exc:
            QMessageBox.warning(self, "OTA 流程出錯", str(exc))
        finally:
            self._starting_ota = False
            self.menu_page.setEnabled(True)

    def _show_disconnect_ui(self):
        if self._closing or self._starting_ota:
            return
        if self.stack.currentWidget() is self.pru_page:
            if self.pru_page.controller:
                self.pru_page.controller.on_disconnected()
            return
        if self.stack.currentWidget() is self.ota_page:
            self.ota_page.on_disconnected()
            self.stack.setEnabled(False)
            self._disconnect_cleanup = asyncio.create_task(self._finish_ota_disconnect())
            return
        self.info_page.cancel_pending_notify()
        self.stack.setCurrentWidget(self.scan_page)
        self.scan_page.status_label.setText("裝置已斷線，請重新掃描連線。")

    async def _finish_ota_disconnect(self):
        try:
            await self.ota_page.close_session()
            self.stack.setCurrentWidget(self.scan_page)
            self.scan_page.status_label.setText("OTA 裝置已斷線，請重新掃描並確認韌體版本。")
        finally:
            self.stack.setEnabled(True)

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        event.ignore()
        if not self._closing:
            self._closing = True
            asyncio.ensure_future(self._shutdown())

    async def _shutdown(self):
        try:
            await self.ota_page.close_session()
            if self._disconnect_cleanup:
                await self._disconnect_cleanup
            task = self.pru_page.leave_page()
            if task:
                await task
            await self.info_page.leave_page()
            await self.ble.disable_all_notify()
            await self.ble.disconnect_all()
        finally:
            self._closed = True
            self.close()
