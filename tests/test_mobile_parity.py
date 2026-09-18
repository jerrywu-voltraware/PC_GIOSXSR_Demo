"""Golden packets come from the supplied Flutter source, not PC constants."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import re
import struct
import unittest
from types import SimpleNamespace

from app.constants import *
from app.protocol import parse_pru_dynamic, parse_pru_static
from app.pru_controller import PruController
from app.ota import OtaTransfer, OTA_SERVICE_UUID, NEW_IMAGE_UUID, IMAGE_CONTENT_UUID, IMAGE_SEQ_UUID, data_packet, handshake

ROOT = Path(__file__).resolve().parents[1]


class FakeGatt:
    def __init__(self):
        self.is_connected = True
        self.target = True
        self.events = []
        self.active = self.max_active = 0
        self.delay = 0
        self.dynamic_raw = bytes(20)
        self.fail_reads = False
        self.fail_connects = 0
        self.fail_notify = False
        self.write_error = None
        self.callback = None

    @asynccontextmanager
    async def operation(self, event):
        self.events.append(event)
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(self.delay)
            yield
        finally:
            self.active -= 1

    def set_notification_callback(self, callback):
        self.callback = callback

    async def discover(self):
        async with self.operation("discover"):
            pass

    def find_target_service(self):
        return object() if self.target else None

    async def enable_notify(self, uuid):
        async with self.operation(("notify", uuid)):
            if self.fail_notify:
                raise RuntimeError("notify failed")

    async def disable_all_notify(self):
        async with self.operation("notify off"):
            pass

    async def reconnect(self):
        async with self.operation("connect"):
            if self.fail_connects:
                self.fail_connects -= 1
                raise RuntimeError("connect failed")
            self.is_connected = True

    async def read_pru(self, uuid):
        async with self.operation(("read", uuid)):
            if self.fail_reads:
                raise RuntimeError("read failed")
            return bytes(20) if uuid == UUID_PRU_STATIC_READ else self.dynamic_raw

    async def write_pru(self, uuid, payload):
        async with self.operation(("write", uuid, bytes(payload))):
            if self.write_error:
                raise self.write_error


class ProtocolTests(unittest.TestCase):
    def test_every_command_matches_flutter_source(self):
        source = (ROOT / "tests/fixtures/mobile_pru_protocol.dart").read_text(encoding="utf-8")
        commands = re.findall(r"PruCommand\('([^']+)',\s*\[(.*?)\]\)", source, re.S)
        actual = {**PACKET_STATIC_PARAMETER, **PACKET_CONTROL}
        self.assertEqual(len(commands), 16)
        for label, body in commands:
            expected = [int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]+", body)]
            self.assertEqual(actual[label], expected, label)

    def test_known_static_and_dynamic_values(self):
        raw = list(range(20))
        s = parse_pru_static(raw)
        self.assertEqual((s.prect_max_mw, s.vrect_min_static_mv, s.vrect_high_static_mv, s.vrect_set_mv),
                         (7000, 23120, 28260, 33400))
        self.assertEqual(s.delta_r1_ohm, 38.54)
        d = parse_pru_dynamic(raw)
        self.assertEqual((d.vrect_mv, d.irect_ma, d.vout_mv, d.iout_ma, d.temperature_c),
                         (5130, 1027, 15410, 2055, -31))
        self.assertEqual((d.vrect_min_mv, d.vrect_set_mv, d.vrect_high_mv, d.pru_alert, d.tester_cmd),
                         (28260, 33400, 38540, 16, 17))

    def test_short_packets_rejected(self):
        for parse in (parse_pru_static, parse_pru_dynamic):
            for length in (0, 1, 19):
                with self.assertRaises(ValueError):
                    parse(bytes(length))

    def test_independent_capability_bits(self):
        raw = bytearray(20)
        raw[4] = 0x84
        rows = dict(parse_pru_static(raw).as_display_lines())
        self.assertEqual(rows["PTU Test Mode"], "Yes")
        self.assertEqual(rows["NFC receiver"], "Supported")
        self.assertEqual(rows["Separate BTLE radio in PRU"], "Not supported")

    def test_ota_golden_bytes(self):
        self.assertEqual(handshake(0x123456), bytes.fromhex("08 56 34 12 00 00 78 05 10"))
        packet = data_packet(b"\x01\x02", 16, 0x1234, True)
        self.assertEqual(packet, bytes.fromhex("24 01 02 ff ff ff ff ff ff ff ff ff ff ff ff ff ff 01 34 12"))


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ble = FakeGatt()
        self.snacks = []
        self.c = PruController(self.ble, alert_snack=self.snacks.append)
        self.c.notify_delay = 0
        self.c.reconnect_backoff = (0, 0, 0)
        self.c.watch_window = .02

    async def asyncTearDown(self):
        await self.c.close()

    async def ready_paused(self):
        await self.c.init()
        self.c.set_live(False)
        await asyncio.sleep(.001)

    async def test_entry_order_and_automatic_live(self):
        await self.c.init()
        await asyncio.sleep(.005)
        self.assertEqual(self.ble.events[:4], ["discover", ("notify", UUID_PRU_NOTIFY),
                         ("read", UUID_PRU_STATIC_READ), ("read", UUID_PRU_DYNAMIC_READ)])
        self.assertEqual(self.c.live_state, "running")

    async def test_no_target_still_attempts_alert_notify(self):
        self.ble.target = False
        await self.c.init()
        self.assertIn(("notify", UUID_PRU_NOTIFY), self.ble.events)
        self.assertEqual(self.c.link_state, "serviceMissing")
        self.assertFalse(self.c.static_loading)
        self.assertFalse(self.c.dynamic_loading)
        self.assertFalse(any(isinstance(e, tuple) and e[0] == "read" for e in self.ble.events))

    async def test_notify_failure_nonfatal_on_initial_entry(self):
        self.ble.fail_notify = True
        await self.c.init()
        self.assertEqual(self.c.link_state, "ready")
        self.assertTrue(any("警報通知啟用失敗" in e[1] for e in self.c.log))

    async def test_gatt_operations_do_not_overlap_and_send_is_guarded(self):
        await self.ready_paused()
        self.ble.delay = .01
        results = await asyncio.gather(self.c.send("control", "DISABLE"),
                                       self.c.send("control", "EN_TIME_SET:0ms"),
                                       self.c.refresh_dynamic(), self.c.refresh_static())
        self.assertEqual(self.ble.max_active, 1)
        self.assertEqual(results[0].phase, "sent")
        self.assertEqual(results[1].error, "另一指令進行中")

    async def test_five_failures_pause_and_last_good_data_retained(self):
        await self.ready_paused()
        await self.c.refresh_dynamic()
        previous = self.c.dynamic
        self.ble.fail_reads = True
        for _ in range(5):
            await self.c.refresh_dynamic()
        self.c.user_wants_live = True
        self.assertEqual(self.c.live_state, "pausedFailures")
        self.assertIs(self.c.dynamic, previous)
        self.c.set_live(True)
        self.assertEqual(self.c.failures, 0)

    async def test_background_and_poll_choices(self):
        await self.ready_paused()
        self.c.set_foreground(False)
        self.c.set_live(True)
        self.assertEqual(self.c.live_state, "pausedBackground")
        count = len(self.ble.events)
        await asyncio.sleep(.01)
        self.assertEqual(len(self.ble.events), count)
        self.c.set_poll_interval(.5)
        self.c.set_poll_interval(.1)
        self.assertEqual(self.c.poll_interval, .5)

    async def test_reconnect_three_attempts_and_manual_retry(self):
        await self.ready_paused()
        self.ble.is_connected = False
        self.ble.fail_connects = 3
        self.c.on_disconnected()
        self.c.on_disconnected()
        await self.c._reconnect_task
        self.assertEqual(self.ble.events.count("connect"), 3)
        self.assertEqual(self.c.link_state, "reconnectFailed")
        self.c.reconnect()
        await self.c._reconnect_task
        self.assertEqual(self.c.link_state, "ready")
        self.assertEqual(self.c.live_state, "pausedByUser")

    async def test_all_alerts_recorded_but_snack_throttled(self):
        for _ in range(25):
            self.c.on_notification(UUID_PRU_NOTIFY, bytes.fromhex("80 01 02 03 04 05 06"))
        self.assertEqual(self.c.alert_count, 25)
        self.assertEqual(len(self.c.log), 20)
        self.assertEqual(len(self.snacks), 1)
        self.assertIn("01:02:03:04:05:06", self.c.last_alert)
        self.c.on_notification("other", b"\x80")
        self.assertEqual(self.c.alert_count, 25)

    async def test_watch_status_changes_not_measurement_changes(self):
        await self.ready_paused()
        await self.c.refresh_dynamic()
        r = await self.c.send("control", "EN_TIME_SET:0ms")
        raw = bytearray(20)
        raw[1] = 10
        self.ble.dynamic_raw = raw
        await self.c.refresh_dynamic()
        self.assertEqual(r.response, "")
        raw[17] = 1
        await self.c.refresh_dynamic()
        self.assertIn("Tester Cmd 0x00→0x01", r.response)

    async def test_watch_expiry_does_not_mark_write_failed(self):
        await self.ready_paused()
        await self.c.refresh_dynamic()
        r = await self.c.send("control", "DISABLE")
        await asyncio.sleep(.04)
        self.assertEqual(r.phase, "sent")
        self.assertEqual(r.response, "輪詢暫停，無法觀察回應")

    async def test_timeout_and_no_watch_on_failed_write(self):
        await self.ready_paused()
        self.ble.write_error = TimeoutError()
        result = await self.c.send("ptu", next(iter(PACKET_STATIC_PARAMETER)))
        self.assertEqual(result.phase, "timeout")
        self.assertFalse(self.c._watches)

    async def test_shutdown_stops_pending_reads(self):
        await self.c.init()
        self.c.shutdown()
        await self.c.close()
        count = len(self.ble.events)
        await asyncio.sleep(.02)
        self.assertEqual(len(self.ble.events), count)


class FakeOtaGatt(FakeGatt):
    def __init__(self, errors=()):
        super().__init__()
        self.client = SimpleNamespace(mtu_size=23)
        self.packets = []
        self.errors = list(errors)

    def services(self):
        return [SimpleNamespace(uuid=OTA_SERVICE_UUID, characteristics=[SimpleNamespace(uuid=u)
                for u in (NEW_IMAGE_UUID, IMAGE_CONTENT_UUID, IMAGE_SEQ_UUID)])]

    async def write(self, char, payload, response=True):
        self.packets.append((char.uuid, bytes(payload), response))
        if char.uuid == NEW_IMAGE_UUID:
            self.callback(IMAGE_SEQ_UUID, bytes(4))
        elif payload[-3]:
            sequence = int.from_bytes(payload[-2:], "little")
            error = self.errors.pop(0) if self.errors else 0
            expected = 0 if error else sequence + 1
            self.callback(IMAGE_SEQ_UUID, struct.pack("<HH", expected, error))


class OtaTests(unittest.IsolatedAsyncioTestCase):
    async def test_window_ack_checksum_retry_and_sequence_resync(self):
        for errors in ((), (15,), (240,)):
            ble = FakeOtaGatt(errors)
            progress = []
            transfer = OtaTransfer(ble, lambda fraction, text: progress.append(fraction))
            transfer.settle_delay = transfer.packet_delay = 0
            await transfer.run(bytes(range(150)))
            self.assertEqual(ble.packets[0], (NEW_IMAGE_UUID, handshake(150), True))
            data = [p for u, p, response in ble.packets if u == IMAGE_CONTENT_UUID]
            self.assertTrue(all(len(p) == 20 for p in data))
            self.assertEqual(data[7][-3], 1)
            self.assertEqual(data[-1][7:17], b"\xff" * 10)
            self.assertEqual(progress[-1], 1)
            self.assertEqual(ble.events[-1], "notify off")

    async def test_short_ack_and_unknown_error(self):
        ble = FakeOtaGatt((99,))
        transfer = OtaTransfer(ble)
        transfer.settle_delay = transfer.packet_delay = 0
        with self.assertRaisesRegex(RuntimeError, "99"):
            await transfer.run(bytes(20))
        transfer._prepare_ack()
        transfer.on_notification(IMAGE_SEQ_UUID, b"\x00")
        with self.assertRaises(ValueError):
            await transfer._wait_ack()


if __name__ == "__main__":
    unittest.main()
