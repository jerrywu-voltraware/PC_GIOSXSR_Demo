"""Desktop routes matching the mobile app; no DAC tool."""
from __future__ import annotations
import asyncio
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox, QLabel, QPushButton
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
        self.setWindowTitle(f"GIOS BLE SR · Debug 工作台 v{APP_VERSION}")
        self.resize(960, 850)
        self.ble = BleManager()
        self.ble.set_disconnected_callback(self.disconnected.emit)
        self.disconnected.connect(self._show_disconnect_ui)
        self._closing = False
        self._closed = False
        self._starting_ota = False
        self._disconnect_cleanup = None
        self.update_controller = UpdateController(self)
        self.update_action = QAction("Check for updates", self)
        self.update_action.triggered.connect(lambda: self.update_controller.check_for_updates(manual=True))
        self.menuBar().addMenu("Help").addAction(self.update_action)
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
        self.pru_page.session_changed.connect(self._update_session_status)
        self.session_status = QLabel()
        self.session_status.setTextFormat(Qt.TextFormat.PlainText)
        self.session_status.setWordWrap(True)
        self.session_return = QPushButton("返回除錯工作台")
        self.session_return.clicked.connect(self._open_pru)
        self.statusBar().addWidget(self.session_status, 1)
        self.statusBar().addPermanentWidget(self.session_return)
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(1000)
        self._session_timer.timeout.connect(self._update_session_status)
        self._session_timer.start()
        self._update_session_status()
        QApplication.instance().applicationStateChanged.connect(self._application_state)
        if check_updates:
            QTimer.singleShot(1500, self.update_controller.check_for_updates)

    @property
    def recording_active(self):
        controller = self.pru_page.controller
        return bool((controller and controller.recording) or self.pru_page.recording_busy)

    def _update_session_status(self):
        active = self.recording_active
        self.scan_page.set_device_actions_locked(active or self._closing)
        reason = "紀錄期間保留目前裝置與警報通知；請先停止紀錄。" if active else ""
        for button in (self.menu_page.info_btn, self.menu_page.ota_btn):
            button.setEnabled(not active and not self._closing)
            button.setToolTip(reason)
        self.update_action.setEnabled(not active and not self._closing)
        self.session_return.setVisible(active and self.stack.currentWidget() is not self.pru_page)
        controller = self.pru_page.controller
        recorder = controller.recorder if controller else None
        if active and recorder:
            if recorder.error:
                text = f"儲存失敗：{recorder.error} · {recorder.path}"
                color = "#c62828"
            else:
                collecting = {"running": "收集中", "pausedByUser": "收集已暫停",
                              "pausedFailures": "讀取失敗已暫停", "pausedLink": "連線中斷",
                              "pausedBackground": "背景暫停"}.get(controller.live_state, controller.live_state)
                text = f"紀錄中 · {collecting} · 已存 {recorder.sample_count} 筆量測 · {recorder.path}"
                color = "#116360"
            self.session_status.setText(text)
            self.session_status.setStyleSheet(f"color: {color};")
        elif active:
            self.session_status.setText("正在準備或結束紀錄，請稍候…")
        else:
            self.session_status.clear()
        self.statusBar().setVisible(active)

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
        self.pru_page.device_name = name
        self.pru_page.device_address = address
        if name == "OTAServiceMgr":
            self.stack.setCurrentWidget(self.ota_page)
            self.ota_page.enter_page()
        else:
            self.stack.setCurrentWidget(self.menu_page)

    def _open_info(self):
        if self.recording_active or self._closing:
            return
        self.stack.setCurrentWidget(self.info_page)

    def _open_pru(self):
        if self._closing or self.pru_page.recording_busy:
            return
        self.stack.setCurrentWidget(self.pru_page)
        self.pru_page.enter_page()
        self._update_session_status()

    @asyncSlot()
    async def _back_to_menu(self):
        if self._closing or self.pru_page.recording_busy:
            return
        source = self.stack.currentWidget()
        task = self.pru_page.leave_page()
        if task:
            await task
        if source is self.info_page:
            await self.info_page.leave_page()
        self.stack.setCurrentWidget(self.menu_page)
        self._update_session_status()

    @asyncSlot()
    async def _back_to_scan(self):
        if self._closing or self.pru_page.recording_busy:
            return
        source = self.stack.currentWidget()
        task = self.pru_page.leave_page()
        if task:
            await task
        if source is self.info_page:
            await self.info_page.leave_page()
        self.stack.setCurrentWidget(self.scan_page)
        self._update_session_status()

    @asyncSlot()
    async def _disconnect_and_back(self):
        if self.recording_active or self._closing:
            return
        task = self.pru_page.leave_page()
        if task:
            await task
        await self.info_page.leave_page()
        await self.ble.disable_all_notify()
        await self.ble.disconnect()
        self.stack.setCurrentWidget(self.scan_page)

    @asyncSlot()
    async def _start_ota(self):
        if self._starting_ota or self.recording_active or self._closing:
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
        if self.stack.currentWidget() is self.pru_page or self.recording_active:
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
        self._closing = True
        self._session_timer.stop()
        self.stack.setEnabled(False)
        self._update_session_status()
        errors = []
        waiting_for_storage = self.pru_page.recording_busy or self.pru_page._export_busy
        try:
            await self.pru_page.wait_recording_operation()
            if waiting_for_storage and self.pru_page._record_error:
                errors.append(self.pru_page._record_error)
        except Exception as exc:
            errors.append(str(exc))
        try:
            await self.ota_page.close_session()
            if self._disconnect_cleanup:
                await self._disconnect_cleanup
        except Exception as exc:
            errors.append(str(exc))
        try:
            task = self.pru_page.leave_page(force=True)
            if task:
                await task
        except Exception as exc:
            errors.append(str(exc))
        try:
            await self.info_page.leave_page()
            await self.ble.disable_all_notify()
        except Exception as exc:
            errors.append(str(exc))
        try:
            await self.ble.disconnect_all()
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            controller = self.pru_page.controller
            recorder = controller.recorder if controller else None
            path = f"\n紀錄檔：{recorder.path}" if recorder else ""
            QMessageBox.warning(self, "結束時發生錯誤", "\n".join(errors) + path +
                                "\n請保留紀錄檔檢查；失敗的資料不可視為已保存。")
        self._closed = True
        self.close()
