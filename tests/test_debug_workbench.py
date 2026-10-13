"""Offscreen workbench checks using a fake GATT adapter and real recording files."""
import asyncio
from datetime import datetime
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication
from app.constants import UUID_PRU_NOTIFY
from app.pru_controller import PruController
from app.theme import apply_theme
from app.windows.pru_test_page import PruTestPage
from test_mobile_parity import FakeGatt
from test_dynamic_card import model

ARTIFACTS = Path(__file__).resolve().parents[1] / 'artifacts' / 'ux_upgrade_20261013'


class DebugWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workbench-test-', dir=ARTIFACTS)
        self.ble = FakeGatt()
        self.page = PruTestPage(self.ble)
        self.c = PruController(self.ble, self.page._render,
                               self.page._show_alert_snack, self.page._show_link_event)
        self.page.controller = self.c
        self.page.device_name = 'GIOS Debug PRU'
        self.page.device_address = 'AA:BB:CC:DD:EE:FF'
        sample = model()
        self.c.link_state = 'ready'
        self.c.static, self.c.dynamic = sample.static, sample.dynamic
        self.c.static_loading = self.c.dynamic_loading = False
        self.c.static_updated = self.c.dynamic_updated = time.monotonic()
        self.ble.dynamic_raw = bytes(sample.dynamic.raw)
        self.ble.static_raw = bytes(sample.static.raw)
        self.page._render()

    async def asyncTearDown(self):
        closing = self.page.leave_page(force=True)
        if closing:
            await closing
        self.page.close()
        self.temp.cleanup()

    async def test_desktop_layout_keeps_values_commands_events_in_first_screen(self):
        await self.c.start_recording(Path(self.temp.name) / 'layout.sqlite')
        self.c.set_live(True)
        await asyncio.sleep(.01)
        self.c.add_marker('開始負載測試')
        await self.c.send('control', 'EN_TIME_SET:0ms')
        await self.c.recorder.flush()
        self.page._clear_snack()
        self.page._render()
        self.page.resize(960, 850)
        self.page.show()
        self.app.processEvents()
        tiles = list(self.page.dynamic_card.tiles.values())
        self.assertEqual(len({tile.mapTo(self.page, QPoint()).y() for tile in tiles}), 1)
        for widget in tiles + [self.page.ctrl_send_btn, self.page.ptu_send_btn,
                                self.page.enable_btn, self.page.log_view.tree]:
            origin = widget.mapTo(self.page, QPoint())
            self.assertTrue(widget.isVisible(), widget.objectName())
            self.assertGreaterEqual(origin.x(), 0)
            self.assertLessEqual(origin.x() + widget.width(), self.page.width())
            self.assertLessEqual(origin.y() + widget.height(), self.page.height())
        self.assertTrue(self.page.dynamic_card.details.isHidden())
        self.assertTrue(self.page.grab().save(str(ARTIFACTS / 'workbench-960x850.png')))
        self.page.resize(1280, 900)
        self.app.processEvents()
        self.assertTrue(self.page.grab().save(str(ARTIFACTS / 'workbench-1280x900.png')))

    async def test_freeze_keeps_measurements_and_raw_but_surfaces_new_errors(self):
        self.page.freeze_btn.setChecked(True)
        raw_before = self.page.raw_label.text()
        self.ble.dynamic_raw = bytes(model(5500).dynamic.raw)
        await self.c.refresh_dynamic()
        self.assertEqual(self.c.dynamic.vrect_mv, 5500)
        self.assertEqual(self.page.dynamic_card.tiles['VRECT'].value_label.text(), '5000')
        self.assertEqual(self.page.raw_label.text(), raw_before)
        self.ble.fail_reads = True
        await self.c.refresh_dynamic()
        self.assertIn('read failed', self.page.dynamic_card.failure_label.text())
        self.assertFalse(self.page.dynamic_card.failure_label.isHidden())
        self.c.on_notification(UUID_PRU_NOTIFY, b'\x80')
        self.assertIn('0x80', self.page.snack.text())
        self.assertEqual(self.page.log_view.tree.topLevelItemCount(), len(self.c.log))
        self.page.freeze_btn.setChecked(False)
        self.assertEqual(self.page.dynamic_card.tiles['VRECT'].value_label.text(), '5500')
        self.assertNotEqual(self.page.raw_label.text(), raw_before)

    async def test_live_events_show_full_buffer_page_search_and_preserve_selection(self):
        for index in range(125):
            self.c.add_marker(f'marker {index:03d}')
        view = self.page.log_view
        self.assertEqual(view.tree.topLevelItemCount(), 100)
        self.assertTrue(view.next_btn.isEnabled())
        view.next_btn.click()
        self.assertEqual(view.tree.topLevelItemCount(), 25)
        view.tree.setCurrentItem(view.tree.topLevelItem(3))
        selected = view.tree.currentItem().text(2)
        self.page._render()
        self.assertEqual(view.tree.currentItem().text(2), selected)
        view.copy_btn.click()
        self.assertIn(selected, QApplication.clipboard().text())
        view.search_edit.setText('marker 02')
        view._filters_changed()
        self.assertEqual(view.tree.topLevelItemCount(), 10)
        self.assertIn('10 筆', view.older.text())

    async def test_recording_file_filters_all_events_and_can_export_csv(self):
        path = Path(self.temp.name) / 'session.sqlite'
        with patch('app.windows.pru_test_page.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            await self.page._toggle_recording()
        self.assertTrue(self.c.recording)
        self.c.set_live(False)
        for index in range(125):
            self.c.add_marker(f'persistent {index:03d}')
        await self.page._toggle_recording()
        self.assertFalse(self.c.recording)
        view = self.page.log_view
        self.assertEqual(view.source_combo.currentData(), 'recording')
        view.kind_combo.setCurrentIndex(view.kind_combo.findData('marker'))
        self.assertEqual(view.tree.topLevelItemCount(), 100)
        view.next_btn.click()
        self.assertEqual(view.tree.topLevelItemCount(), 25)
        view.search_edit.setText('persistent 02')
        view._filters_changed()
        self.assertEqual(view.tree.topLevelItemCount(), 10)
        self.assertIn('已寫入', self.page.record_status.text())
        destination = Path(self.temp.name) / 'session.csv'
        with patch('app.windows.pru_test_page.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            await self.page._export_csv()
        self.assertTrue(destination.exists())
        self.assertIn('persistent 024', destination.read_text(encoding='utf-8-sig'))

    async def test_recording_continues_while_frozen_and_page_hidden(self):
        path = Path(self.temp.name) / 'background.sqlite'
        await self.c.start_recording(path)
        self.c.set_live(False)
        self.page.freeze_btn.setChecked(True)
        self.assertIsNone(self.page.leave_page())
        self.assertFalse(self.c.disposed)
        await self.c.refresh_dynamic()
        await self.page.enter_page()
        self.assertIs(self.page.controller, self.c)
        self.assertTrue(self.page._age_timer.isActive())
        self.assertTrue(self.page.freeze_btn.isChecked())
        await self.c.stop_recording()
        self.assertGreaterEqual(self.c.recorder.sample_count, 1)

    async def test_existing_recording_file_is_never_overwritten(self):
        path = Path(self.temp.name) / 'existing.sqlite'
        path.write_bytes(b'existing-data')
        with patch('app.windows.pru_test_page.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            await self.page._toggle_recording()
        self.assertEqual(path.read_bytes(), b'existing-data')
        self.assertFalse(self.c.recording)
        self.assertIn('檔案已存在', self.page.record_error.text())
        self.assertFalse(self.page.record_error.isHidden())

    async def test_recording_operation_disables_back_and_waits_before_completion(self):
        path = Path(self.temp.name) / 'delayed.sqlite'
        original = self.c.start_recording
        gate = asyncio.Event()
        async def delayed(*args, **kwargs):
            await gate.wait()
            return await original(*args, **kwargs)
        with patch.object(self.c, 'start_recording', delayed), patch(
                'app.windows.pru_test_page.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            operation = self.page._toggle_recording()
            await asyncio.sleep(0)
            self.assertTrue(self.page.recording_busy)
            self.assertFalse(self.page.back_btn.isEnabled())
            waiter = asyncio.create_task(self.page.wait_recording_operation())
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            gate.set()
            await waiter
            await operation
        self.assertFalse(self.page.recording_busy)
        self.assertTrue(self.page.back_btn.isEnabled())

    async def test_export_operation_is_awaited_before_shutdown(self):
        await self.c.start_recording(Path(self.temp.name) / 'export-wait.sqlite')
        await self.c.stop_recording()
        gate = asyncio.Event()
        original = self.c.recorder.export_csv
        async def delayed(destination):
            await gate.wait()
            return await original(destination)
        destination = Path(self.temp.name) / 'export-wait.csv'
        with patch.object(self.c.recorder, 'export_csv', delayed), patch(
                'app.windows.pru_test_page.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            operation = self.page._export_csv()
            await asyncio.sleep(0)
            waiter = asyncio.create_task(self.page.wait_recording_operation())
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            gate.set()
            await waiter
            await operation
        self.assertTrue(destination.exists())
        self.assertIsNone(self.page._export_task)

    async def test_storage_error_is_latched_and_visible_after_stop(self):
        await self.c.start_recording(Path(self.temp.name) / 'error.sqlite')
        self.c.recorder._fail(RuntimeError('simulated disk error'))
        self.page.freeze_btn.setChecked(True)
        self.page._render()
        self.assertIn('simulated disk error', self.page.record_error.text())
        self.assertIn('保存異常', self.page.record_status.text())
        await self.page._toggle_recording()
        self.page._clear_snack()
        self.page._render()
        self.assertFalse(self.c.recording)
        self.assertFalse(self.page.record_error.isHidden())
        self.assertIn('simulated disk error', self.page.record_error.text())

    async def test_recorded_timestamps_use_local_time_and_collection_filter_exists(self):
        await self.c.start_recording(Path(self.temp.name) / 'time.sqlite')
        self.c.add_marker('timestamp check')
        await self.c.stop_recording()
        view = self.page.log_view
        view.source_combo.setCurrentIndex(1)
        row = view.tree.topLevelItem(0)
        raw_time = row.toolTip(0)
        expected = datetime.fromisoformat(raw_time).astimezone().strftime('%m-%d %H:%M:%S.%f')[:-3]
        self.assertEqual(row.text(0), expected)
        self.assertGreaterEqual(view.kind_combo.findData('collection'), 0)

    async def test_queued_enter_cannot_resurrect_controller_during_shutdown(self):
        gate = asyncio.Event()
        original = self.c.close
        async def delayed_close():
            await gate.wait()
            await original()
        with patch.object(self.c, 'close', delayed_close):
            first_close = self.page.leave_page()
            entering = self.page.enter_page()
            await asyncio.sleep(0)
            self.assertFalse(entering.done())
            final_close = self.page.leave_page(force=True)
            gate.set()
            await first_close
            await final_close
            await entering
        self.assertIs(self.page.controller, self.c)
        self.assertTrue(self.c.disposed)
        self.assertFalse(self.page._age_timer.isActive())
        await self.page.enter_page()
        self.assertIs(self.page.controller, self.c)


if __name__ == '__main__':
    unittest.main()
