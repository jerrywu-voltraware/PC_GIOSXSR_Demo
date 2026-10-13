"""Mobile behavior regressions for PRU feedback and page interactions."""
import asyncio
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from app.constants import PACKET_CONTROL, UUID_PRU_CONTROL, UUID_PRU_NOTIFY
from app.protocol import parse_pru_dynamic, parse_pru_static
from app.pru_controller import PruController
from app.theme import apply_theme
from app.windows.pru_test_page import PruTestPage
from app.windows.pru_widgets import ERROR, SUCCESS, INFO, MUTED
from test_mobile_parity import FakeGatt


class PruFeedbackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    async def asyncSetUp(self):
        self.ble = FakeGatt()
        self.page = PruTestPage(self.ble)
        self.c = PruController(self.ble, self.page._render, self.page._show_alert_snack, self.page._show_link_event)
        self.page.controller = self.c
        self.c.link_state = 'ready'
        self.c.static_loading = self.c.dynamic_loading = False
        self.c.static = parse_pru_static(bytes(20))
        self.c.dynamic = parse_pru_dynamic(bytes(20))
        self.c.static_updated = self.c.dynamic_updated = time.monotonic()
        self.page._render()

    async def asyncTearDown(self):
        closing = self.page.leave_page()
        if closing:
            await closing
        self.page.close()

    async def test_mixed_alert_colors_and_clear(self):
        raw = bytearray(20)
        raw[16] = 0x88
        self.c.dynamic = parse_pru_dynamic(raw)
        self.page._render()
        card = self.page.dynamic_card
        self.assertFalse(card.alert_bits.isHidden())
        self.assertTrue(card.no_alert.isHidden())
        self.assertEqual(len(card.alert_bits.chips), 8)
        self.assertIn(ERROR, card.alert_bits.chips[0].styleSheet())
        self.assertIn(SUCCESS, card.alert_bits.chips[4].styleSheet())
        self.assertIn(MUTED, card.alert_bits.chips[1].styleSheet())
        raw[16] = 0x07
        self.c.dynamic = parse_pru_dynamic(raw)
        self.page._render()
        for chip in card.alert_bits.chips[5:]:
            self.assertIn(INFO, chip.styleSheet())
        raw[16] = 0
        self.c.dynamic = parse_pru_dynamic(raw)
        self.page._render()
        self.assertTrue(card.alert_bits.isHidden())
        self.assertFalse(card.no_alert.isHidden())

    async def test_notification_detail_keeps_original_snapshot_and_severity(self):
        first = bytearray.fromhex('80 01 02 03 04 05 06')
        self.c.on_notification(UUID_PRU_NOTIFY, first)
        first[0] = 0
        self.c.on_notification(UUID_PRU_NOTIFY, bytes.fromhex('08 AA BB CC DD EE FF'))
        self.assertEqual(self.c.alert_count, 2)
        self.assertEqual([entry.level for entry in self.c.log], ['warning', 'error'])
        self.assertIn('0x80', self.page.snack.text())
        self.assertEqual(self.page.snack.property('level'), 'warning')
        self.assertEqual(self.page._snack_timer.interval(), 5000)
        self.page.snack_action_btn.click()
        detail = self.page._alert_dialog.text()
        self.assertIn('0x80', detail)
        self.assertIn('01:02:03:04:05:06', detail)
        self.assertIn('PRU Over-Voltage', detail)
        self.assertNotIn('AA:BB', detail)
        self.c.on_notification(UUID_PRU_NOTIFY, b'\x00')
        self.assertEqual(self.c.log[0].level, 'info')
        self.assertEqual(self.page._alert_dialog.text(), detail)
        self.c._last_snack -= 5
        self.c.on_notification(UUID_PRU_NOTIFY, b'\x01')
        self.assertIn('Mode Transition Bit 0', self.page.snack.text())

    async def test_read_timeout_is_visible_and_retains_data(self):
        static, dynamic = self.c.static, self.c.dynamic
        async def timeout(uuid):
            raise TimeoutError()
        self.ble.read_pru = timeout
        await self.c.refresh_static()
        await self.c.refresh_dynamic()
        self.assertIs(self.c.static, static)
        self.assertIs(self.c.dynamic, dynamic)
        self.assertIn('逾時 5 s', self.page.static_card.status.text())
        self.assertIn('逾時 5 s', self.page.dynamic_card.failure_label.text())
        self.c.static = self.c.dynamic = None
        self.page._render()
        self.assertIn('逾時 5 s', self.page.dynamic_card.status.text())
        self.assertIn('逾時 5 s', self.page.static_card.status.text())

    async def test_failed_command_retry_uses_original_payload(self):
        original = 'EN_TIME_SET:20ms'
        self.ble.write_error = RuntimeError('write rejected')
        await self.page._send_label('control', original)
        self.assertEqual(self.page.snack_action_btn.text(), '重試')
        self.assertEqual(self.page._snack_timer.interval(), 4000)
        self.assertEqual(self.c.log[0].level, 'error')
        self.assertIn('9a67', self.c.log[0].detail)
        self.assertIn('5 B: C0 00 02 00 00', self.c.log[0].detail)
        self.page.ctrl_combo.setCurrentText('DISABLE')
        self.ble.write_error = None
        self.page.snack_action_btn.click()
        await asyncio.sleep(.02)
        writes = [e for e in self.ble.events if isinstance(e, tuple) and e[0] == 'write']
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0], writes[1])
        self.assertEqual(writes[-1], ('write', UUID_PRU_CONTROL, bytes(PACKET_CONTROL[original])))
        self.assertEqual(self.page.snack.property('level'), 'success')
        self.assertEqual(self.page._snack_timer.interval(), 3000)
        self.assertTrue(self.page.snack_action_btn.isHidden())

    async def test_timeout_warning_does_not_offer_failed_retry(self):
        self.ble.write_error = TimeoutError()
        await self.page._send_label('control', 'DISABLE')
        self.assertIn('逾時', self.page.snack.text())
        self.assertEqual(self.page.snack.property('level'), 'warning')
        self.assertTrue(self.page.snack_action_btn.isHidden())
        self.assertEqual(self.c.log[0].level, 'warning')
        self.assertIn('5 B:', self.c.log[0].detail)

    async def test_send_preview_locking_and_watch_feedback(self):
        self.page.ctrl_combo.setCurrentText('EN_TIME_SET:20ms')
        self.assertEqual(self.page._previews['control'].text(), '5 B: C0 00 02 00 00')
        self.ble.delay = .03
        sending = self.page._send_label('control', 'EN_TIME_SET:20ms')
        await asyncio.sleep(.005)
        self.assertFalse(self.page.ctrl_combo.isEnabled())
        self.assertFalse(self.page.ptu_combo.isEnabled())
        self.assertFalse(self.page.ctrl_send_btn.isEnabled())
        self.assertIn('寫入中', self.page.ctrl_result.text())
        await sending
        self.assertTrue(self.page.ctrl_combo.isEnabled())
        self.assertIn('寫入完成', self.page.ctrl_result.text())
        self.assertIn('觀察回應中', self.page.ctrl_result.text())

    async def test_static_refresh_clicks_do_not_queue_duplicates(self):
        self.ble.delay = .03
        reading = self.page._refresh_static()
        await asyncio.sleep(.005)
        self.assertFalse(self.page.static_card.refresh_btn.isEnabled())
        self.page.static_card.refresh_btn.click()
        await reading
        reads = [e for e in self.ble.events if isinstance(e, tuple) and e[0] == 'read']
        self.assertEqual(len(reads), 1)
        self.assertTrue(self.page.static_card.refresh_btn.isEnabled())

    async def test_static_collapse_capabilities_and_threshold_error(self):
        card = self.page.static_card
        self.assertTrue(card.details.isHidden())
        raw = bytearray(20)
        raw[4], raw[5], raw[6] = 0x84, 0xF1, 0xE3
        raw[8], raw[12], raw[10] = 30, 20, 10
        self.c.static = parse_pru_static(raw)
        self.page._render()
        self.assertIn('HW 0xF1', card.expand_btn.text())
        card.expand_btn.click()
        self.page._render()
        self.assertFalse(card.details.isHidden())
        self.assertEqual([i for i, b in enumerate(card.bits.chips) if b.property('active')], [0, 5])
        self.assertEqual(len(card.bits.chips), 8)
        rows = {card.tree.topLevelItem(i).text(0): card.tree.topLevelItem(i) for i in range(card.tree.topLevelItemCount())}
        self.assertEqual(rows['Hardware rev'].text(1), '0xF1 (241)')
        self.assertFalse(card.inconsistent.isHidden())
        for key in ('VRECT_MIN_STATIC', 'VRECT_SET', 'VRECT_HIGH_STATIC'):
            self.assertEqual(rows[key].foreground(1).color().name(), ERROR)
        self.c.static_error = '逾時 5 s'
        self.page._render()
        self.assertFalse(card.details.isHidden())
        self.assertIn('更新失敗', card.status.text())

    async def test_link_state_placeholder_and_reconnection_events(self):
        self.page.device_name = 'Test PRU'
        self.c.link_state = 'discovering'
        self.page._render()
        self.assertTrue(self.page.scroll.isHidden())
        self.assertFalse(self.page.page_state.isHidden())
        self.assertFalse(self.page.ctrl_combo.isEnabled())
        self.c._service_missing('missing service')
        self.assertIn('missing service', self.page.page_state.text())
        self.assertFalse(self.page.retry_btn.isHidden())
        self.c.reconnect_backoff = (0, 0, 0)
        self.c.notify_delay = 0
        self.ble.fail_connects = 3
        self.c.on_disconnected()
        await self.c._reconnect_task
        self.assertEqual(self.c.log[0].title, '自動重新連線失敗')
        self.assertEqual(self.c.log[0].level, 'error')
        self.assertEqual(self.page.snack.text(), '自動重新連線失敗')
        self.c.reconnect()
        await self.c._reconnect_task
        self.assertEqual(self.page.snack.text(), '已重新連線')
        self.assertEqual(self.page.snack.property('level'), 'success')
        self.assertIn('Test PRU', self.page.status_banner.text())
        self.assertFalse(self.page.scroll.isHidden())

    async def test_event_rows_and_optional_diagnostics(self):
        for _ in range(25):
            self.c.on_notification(UUID_PRU_NOTIFY, b'\x80')
        view = self.page.log_view
        self.assertEqual(len(self.c.log), 25)
        self.assertEqual(view.tree.topLevelItemCount(), 25)
        self.assertIn('25', view.older.text())
        self.assertEqual(view.tree.topLevelItem(0).data(2, Qt.ItemDataRole.UserRole), 'error')
        self.assertTrue(self.page.diagnostics.isHidden())
        self.page.diagnostic_btn.click()
        self.assertFalse(self.page.diagnostics.isHidden())
        self.assertIn('25 筆', self.page.alert_label.text())
        self.assertIn('Static RAW', self.page.raw_label.text())
        self.assertIn('Dynamic RAW', self.page.raw_label.text())

    async def test_leaving_page_discards_actions_and_late_write_feedback(self):
        self.c.on_notification(UUID_PRU_NOTIFY, b'\x80')
        self.page.snack_action_btn.click()
        self.assertIsNotNone(self.page._alert_dialog)
        self.ble.delay = .03
        self.ble.write_error = RuntimeError('late failure')
        pending = self.page._send_label('control', 'DISABLE')
        await asyncio.sleep(.005)
        closing = self.page.leave_page()
        await pending
        await closing
        self.assertIsNone(self.page._alert_dialog)
        self.assertIsNone(self.page._snack_action)
        self.assertTrue(self.page.snack_box.isHidden())


if __name__ == '__main__':
    unittest.main()
