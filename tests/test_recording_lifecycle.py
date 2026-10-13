"""Session ownership regressions with fake BLE, no network or devices."""
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidgetItem
from app.constants import UUID_PRU_NOTIFY
from app.pru_controller import PruController
from app.updater import UpdateController
from app.windows.main_window import MainWindow
from test_mobile_parity import FakeGatt


async def until(predicate, timeout=3):
    async def wait():
        while not predicate():
            await asyncio.sleep(.01)
    await asyncio.wait_for(wait(), timeout)


class RecordingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.sqlite3'
        self.delay_patch = patch.object(PruController, 'notify_delay', 0)
        self.delay_patch.start()
        with patch('app.windows.main_window.UpdateController'):
            self.window = MainWindow(check_updates=False)
        self.ble = FakeGatt()
        self.ble.address = 'AA:BB'
        self.ble.device_names = {'AA:BB': 'Test PRU'}
        self.ble.connected_devices = lambda: [('AA:BB', 'Test PRU')]
        self.ble.services = lambda: []
        async def disconnect():
            self.ble.events.append('disconnect all')
            self.ble.is_connected = False
        self.ble.disconnect = self.ble.disconnect_all = disconnect
        for owner in (self.window, self.window.scan_page, self.window.pru_page,
                      self.window.info_page, self.window.ota_page):
            owner.ble = self.ble
        self.window.show()
        self.window._on_connected('AA:BB', 'Test PRU')
        self.window._open_pru()
        await until(lambda: self.window.pru_page.controller is not None and
                    self.window.pru_page.controller.dynamic is not None)
        self.c = self.window.pru_page.controller
        self.c.set_poll_interval(.5)
        self.c.reconnect_backoff = (0, 0, 0)

    async def asyncTearDown(self):
        try:
            if not self.window._closed:
                with patch('app.windows.main_window.QMessageBox.warning'):
                    await self.window._shutdown()
        finally:
            self.delay_patch.stop()
            self.temp.cleanup()

    async def start_recording(self):
        recorder = await self.c.start_recording(self.path)
        self.window._update_session_status()
        return recorder

    async def test_recording_survives_navigation_background_and_reconnect(self):
        recorder = await self.start_recording()
        notifications_off = self.ble.events.count('notify off')
        await self.window._back_to_menu()
        await self.window._back_to_scan()
        self.assertIs(self.window.pru_page.controller, self.c)
        self.assertFalse(self.c.disposed)
        self.assertEqual(self.ble.events.count('notify off'), notifications_off)
        self.c.set_foreground(False)
        self.assertEqual(self.c.live_state, 'running')
        await until(lambda: recorder.sample_count >= 2)
        self.ble.callback(UUID_PRU_NOTIFY, b'\x80')
        self.ble.is_connected = False
        self.window._show_disconnect_ui()
        await self.c._reconnect_task
        self.assertEqual(self.c.link_state, 'ready')
        self.assertIs(self.c.recorder, recorder)
        await recorder.flush()
        rows, count = recorder.query_events(kind='alert')
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]['raw_hex'], '80')
        self.window._open_pru()
        await asyncio.sleep(.02)
        self.assertIs(self.window.pru_page.controller, self.c)
        self.assertEqual(self.c.poll_interval, .5)

    async def test_recording_guards_device_switch_info_ota_and_updates(self):
        await self.start_recording()
        await self.window._back_to_scan()
        scan = self.window.scan_page
        item = QListWidgetItem('Other PRU')
        item.setData(Qt.ItemDataRole.UserRole, ('CC:DD', 'Other PRU'))
        scan.list_widget.addItem(item)
        scan.list_widget.setCurrentItem(item)
        before = list(self.ble.events)
        await scan._connect_to_item(item)
        await scan._disconnect_selected()
        self.window._open_info()
        with patch('app.windows.main_window.QMessageBox.question') as question:
            await self.window._start_ota()
            question.assert_not_called()
        self.assertEqual(self.ble.events, before)
        self.assertIs(self.window.stack.currentWidget(), scan)
        self.assertFalse(scan.connect_btn.isEnabled())
        self.assertFalse(scan.disconnect_btn.isEnabled())
        self.assertFalse(self.window.menu_page.info_btn.isEnabled())
        self.assertFalse(self.window.menu_page.ota_btn.isEnabled())
        updater = UpdateController(self.window)
        with patch.object(updater, '_start_worker') as worker:
            updater.check_for_updates(manual=True)
            worker.assert_not_called()
        with patch('app.updater.QMessageBox.information'), patch('app.updater.subprocess.Popen') as spawn:
            updater._install_update(Path(self.temp.name) / 'new.exe')
            spawn.assert_not_called()
        await self.c.stop_recording()
        self.window._update_session_status()
        self.assertTrue(scan.connect_btn.isEnabled())
        self.assertTrue(scan.disconnect_btn.isEnabled())

    async def test_freeze_holds_display_while_samples_continue(self):
        recorder = await self.start_recording()
        page = self.window.pru_page
        page.freeze_btn.setChecked(True)
        before = page.dynamic_card.tiles['VRECT'].value_label.text()
        raw = bytearray(20)
        raw[1:3] = (500).to_bytes(2, 'little')
        self.ble.dynamic_raw = raw
        await self.c.refresh_dynamic()
        await recorder.flush()
        self.assertGreater(recorder.sample_count, 0)
        self.assertEqual(page.dynamic_card.tiles['VRECT'].value_label.text(), before)
        page.freeze_btn.setChecked(False)
        self.assertEqual(page.dynamic_card.tiles['VRECT'].value_label.text(), '5000')

    async def test_shutdown_drains_writer_and_preserves_all_events(self):
        recorder = await self.start_recording()
        for _ in range(300):
            self.c.on_notification(UUID_PRU_NOTIFY, b'\x80')
        with patch('app.windows.main_window.QMessageBox.warning') as warning:
            await self.window._shutdown()
            warning.assert_not_called()
        self.assertTrue(self.window._closed)
        self.assertTrue(self.c.disposed)
        self.assertFalse(self.c.recording)
        self.assertEqual(recorder.pending_count, 0)
        self.assertFalse(self.ble.is_connected)
        with closing(sqlite3.connect(self.path)) as connection:
            count = connection.execute("SELECT count(*) FROM records WHERE kind='alert'").fetchone()[0]
        self.assertEqual(count, 300)

    async def test_storage_failure_stays_visible_and_shutdown_cleans_up(self):
        recorder = await self.start_recording()
        recorder._fail(OSError('simulated disk full'))
        self.window.pru_page._render()
        self.window._update_session_status()
        self.assertIn('simulated disk full', self.window.session_status.text())
        self.assertFalse(self.window.scan_page.connect_btn.isEnabled())
        with patch('app.windows.main_window.QMessageBox.warning') as warning:
            await self.window._shutdown()
            self.assertIn('simulated disk full', warning.call_args.args[2])
        self.assertTrue(self.window._closed)
        self.assertFalse(self.ble.is_connected)
        self.assertEqual(recorder.pending_count, 0)

    async def test_update_install_uses_window_close_cleanup(self):
        updater = UpdateController(self.window)
        with patch('app.updater.Path.write_text'), patch('app.updater.subprocess.Popen'), \
                patch.object(self.window, 'close') as close, patch('app.updater.QApplication.quit') as quit_app:
            updater._install_update(Path(self.temp.name) / 'new.exe')
            close.assert_called_once()
            quit_app.assert_not_called()

    async def test_shutdown_reports_export_failure_after_waiting(self):
        recorder = await self.start_recording()
        release = asyncio.Event()
        async def fail_export(destination):
            await release.wait()
            raise OSError('simulated export disk failure')
        with patch('app.windows.pru_test_page.QFileDialog.getSaveFileName',
                   return_value=(str(Path(self.temp.name) / 'export.csv'), 'CSV')), \
                patch.object(recorder, 'export_csv', side_effect=fail_export), \
                patch('app.windows.main_window.QMessageBox.warning') as warning:
            exporting = self.window.pru_page._export_csv()
            await until(lambda: self.window.pru_page._export_busy)
            shutting_down = asyncio.create_task(self.window._shutdown())
            await asyncio.sleep(.02)
            self.assertFalse(shutting_down.done())
            release.set()
            await shutting_down
            await exporting
            self.assertIn('simulated export disk failure', warning.call_args.args[2])
        self.assertTrue(self.window._closed)
        self.assertFalse(self.ble.is_connected)


if __name__ == '__main__':
    unittest.main()
