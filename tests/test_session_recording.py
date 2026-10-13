"""Disk read-back and failure tests; no real Bluetooth connection is used."""
import asyncio
import csv
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.constants import UUID_PRU_NOTIFY
from app.protocol import parse_pru_dynamic, parse_pru_static
from app.pru_controller import PruController
from app.session_store import SessionRecorder
from test_mobile_parity import FakeGatt


def sample(validity, vrect, irect, vout=0, iout=0, temperature=0, low=0, target=0, high=0):
    raw = bytearray(20)
    raw[0] = validity
    for offset, value in ((1, vrect), (3, irect), (5, vout), (7, iout),
                          (10, low), (12, target), (14, high)):
        raw[offset:offset + 2] = value.to_bytes(2, "little")
    raw[9] = temperature + 40
    raw[16:18] = bytes((0x80, 0x01))
    return bytes(raw)


class RecorderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "session.sqlite3"
        self.recorders = []

    async def asyncTearDown(self):
        for recorder in self.recorders:
            try:
                await recorder.close()
            except RuntimeError:
                pass
        self.temp.cleanup()

    async def recorder(self, cls=SessionRecorder, **kwargs):
        recorder = await cls.create(self.path, {"device_name": "test PRU", "device_address": "AA:BB"}, **kwargs)
        self.recorders.append(recorder)
        return recorder

    def read_rows(self, record_type=None):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM records WHERE record_type=? ORDER BY id", (record_type,)) if record_type else connection.execute("SELECT * FROM records ORDER BY id")
            return [dict(row) for row in rows]

    async def test_three_known_samples_read_back_with_null_invalid_fields(self):
        recorder = await self.recorder()
        packets = [sample(0x00, 123, 456, 900, 800, 25),
                   sample(0xC0, 234, 567, 345, 678, 26),
                   sample(0xFC, 345, 678, 456, 789, -5, 100, 200, 300)]
        for raw in packets:
            recorder.record_sample(parse_pru_dynamic(raw))
        await recorder.close()
        expected = [(1230, 456, None, None, None, None, None, None),
                    (2340, 567, 3450, 678, None, None, None, None),
                    (3450, 678, 4560, 789, -5, 1000, 2000, 3000)]
        rows = self.read_rows("dynamic")
        fields = ("vrect_mv", "irect_ma", "vout_mv", "iout_ma", "temperature_c",
                  "vrect_min_mv", "vrect_set_mv", "vrect_high_mv")
        for raw, row, values in zip(packets, rows, expected):
            self.assertEqual(tuple(row[key] for key in fields), values)
            self.assertEqual(row["raw_hex"], raw.hex(" ").upper())
            self.assertEqual(row["validity"], raw[0])
            self.assertEqual(row["valid"], 1)
            self.assertRegex(row["at"], r"T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")
            self.assertGreater(row["monotonic"], 0)
        self.assertEqual(recorder.sample_count, 3)
        self.assertEqual(recorder.pending_count, 0)
        print("Known sample SQLite read-back:", [tuple(row[key] for key in fields) for row in rows])

    async def test_over_one_thousand_events_and_search_pagination(self):
        recorder = await self.recorder()
        for index in range(1205):
            self.assertTrue(recorder.record_event(f"event {index}", "payload", kind="marker" if index % 2 else "alert", raw=b"\x80"))
            self.assertLessEqual(recorder.pending_count, recorder.queue_capacity)
        await recorder.close()
        rows, total = recorder.query_events(limit=200)
        self.assertEqual((total, len(rows), recorder.event_count), (1205, 200, 1205))
        self.assertEqual(rows[0]["title"], "event 1204")
        older, count = recorder.query_events(kind="marker", offset=600)
        self.assertEqual(count, 602)
        self.assertEqual(len(older), 2)
        matches, count = recorder.query_events(query="event 1204")
        self.assertEqual(count, 1)
        self.assertEqual(matches[0]["raw_hex"], "80")
        self.assertEqual(recorder.query_events(query="% OR 1=1")[1], 0)

    async def test_csv_includes_events_static_raw_and_protects_strings(self):
        recorder = await self.recorder()
        recorder.record_sample(parse_pru_dynamic(sample(0, 10, 20)))
        recorder.record_static(parse_pru_static(bytes(20)))
        recorder.record_event("=HYPERLINK(1)", "  @SUM(1)", kind="marker", raw=b"\x80\x01")
        destination = Path(self.temp.name) / "session.csv"
        # Export while the session is still open performs a flush and a read snapshot.
        self.assertEqual(await recorder.export_csv(destination), destination)
        with destination.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["record_type"] for row in rows], ["metadata", "dynamic", "static", "event"])
        self.assertEqual(rows[1]["vout_mv"], "")
        self.assertEqual(rows[1]["validity"], "0")
        self.assertEqual(rows[3]["title"], "'=HYPERLINK(1)")
        self.assertEqual(rows[3]["detail"], "'  @SUM(1)")
        self.assertEqual(rows[3]["raw_hex"], "80 01")
        self.assertIsNone(json.loads(rows[2]["data_json"])["delta_r1_ohm"])
        self.assertEqual(json.loads(rows[0]["data_json"])["device_address"], "AA:BB")
        previous = destination.read_bytes()
        with self.assertRaises(FileExistsError):
            await recorder.export_csv(destination)
        self.assertEqual(destination.read_bytes(), previous)

    async def test_existing_database_is_never_overwritten(self):
        sentinel = b"original experiment data"
        self.path.write_bytes(sentinel)
        with self.assertRaises(FileExistsError):
            await self.recorder()
        self.assertEqual(self.path.read_bytes(), sentinel)

    async def test_write_failure_is_latched_and_counters_never_claim_commit(self):
        class FailedRecorder(SessionRecorder):
            def _write_batch(self, connection, batch):
                raise sqlite3.OperationalError("disk full (test injection)")
        recorder = await self.recorder(FailedRecorder)
        recorder.record_sample(parse_pru_dynamic(sample(0, 1, 2)))
        with self.assertRaisesRegex(RuntimeError, "disk full"):
            await recorder.flush()
        self.assertEqual(recorder.sample_count, 0)
        self.assertEqual(self.read_rows(), [])
        self.assertFalse(recorder.record_event("after failure"))
        self.assertEqual(recorder.dropped_count, 2)
        with self.assertRaisesRegex(RuntimeError, "disk full"):
            await recorder.close()
        self.assertFalse(recorder._thread.is_alive())
        self.assertIn("disk full", recorder.error)
        with self.assertRaises(RuntimeError):
            await recorder.export_csv(Path(self.temp.name) / "false-success.csv")

    async def test_queue_bound_overflow_and_close_wait_for_actual_commit(self):
        entered, release = threading.Event(), threading.Event()
        class SlowRecorder(SessionRecorder):
            def _write_batch(self, connection, batch):
                entered.set()
                release.wait(5)
                return super()._write_batch(connection, batch)
        recorder = await self.recorder(SlowRecorder, queue_capacity=4, batch_size=1)
        recorder.record_event("first")
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        self.assertEqual(recorder.event_count, 0)
        for index in range(3):
            self.assertTrue(recorder.record_event(str(index)))
        self.assertEqual(recorder.pending_count, 4)
        self.assertFalse(recorder.record_event("overflow"))
        self.assertIn("queue full", recorder.error)
        closing = asyncio.create_task(recorder.close())
        await asyncio.sleep(.02)
        self.assertFalse(closing.done())
        release.set()
        with self.assertRaisesRegex(RuntimeError, "queue full"):
            await closing
        self.assertEqual((recorder.event_count, recorder.pending_count, recorder.dropped_count), (4, 0, 1))
        self.assertEqual(len(self.read_rows()), 4)
        self.assertFalse(recorder._thread.is_alive())

    async def test_cancelled_close_still_finishes_accepted_rows(self):
        entered, release = threading.Event(), threading.Event()
        class SlowRecorder(SessionRecorder):
            def _write_batch(self, connection, batch):
                entered.set()
                release.wait(5)
                return super()._write_batch(connection, batch)
        recorder = await self.recorder(SlowRecorder)
        recorder.record_event("must survive cancellation")
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        closing_task = asyncio.create_task(recorder.close())
        await asyncio.sleep(.01)
        closing_task.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(closing_task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await closing_task
        self.assertEqual(recorder.event_count, 1)
        self.assertEqual(recorder.pending_count, 0)
        self.assertFalse(recorder._thread.is_alive())
        self.assertEqual(self.read_rows()[0]["title"], "must survive cancellation")

    async def test_cancelled_creation_closes_the_new_writer(self):
        entered, release = threading.Event(), threading.Event()
        instances = []
        class SlowCreateRecorder(SessionRecorder):
            def __init__(self, *args, **kwargs):
                entered.set()
                release.wait(5)
                super().__init__(*args, **kwargs)
                instances.append(self)
        creating = asyncio.create_task(SlowCreateRecorder.create(self.path))
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        creating.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await creating
        self.assertEqual(len(instances), 1)
        self.assertFalse(instances[0]._thread.is_alive())
        self.assertEqual(instances[0].pending_count, 0)


class RecordingControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "controller.sqlite3"
        self.ble = FakeGatt()
        self.ble.address = "AA:BB:CC:DD:EE:FF"
        self.ble.device_names = {self.ble.address: "Fake PRU"}
        self.controller = PruController(self.ble)
        self.controller.link_state = "ready"

    async def asyncTearDown(self):
        try:
            await self.controller.close()
        finally:
            self.temp.cleanup()

    async def test_recording_keeps_background_polling_until_stop(self):
        c = self.controller
        c.set_foreground(False)
        c.set_live(True)
        self.assertEqual(c.live_state, "pausedBackground")
        await c.start_recording(self.path)
        self.assertEqual(c.live_state, "running")
        await asyncio.sleep(.02)
        await c.stop_recording()
        self.assertEqual(c.live_state, "pausedBackground")
        self.assertFalse(c.recording)
        self.assertGreater(c.recorder.sample_count, 0)
        with closing(sqlite3.connect(self.path)) as connection:
            metadata = {key: json.loads(value) for key, value in connection.execute("SELECT * FROM metadata")}
        self.assertEqual(metadata["device_address"], self.ble.address)
        self.assertIn("app_version", metadata)
        self.assertEqual(metadata["poll_interval_seconds"], 1.0)

    async def test_malformed_raw_read_failures_and_automatic_pause_are_saved(self):
        c = self.controller
        await c.start_recording(self.path)
        self.ble.dynamic_raw = b"\x01\x02"
        await c.refresh_dynamic()
        self.ble.static_raw = b"\x04"
        await c.refresh_static()
        self.ble.fail_reads = True
        for _ in range(4):
            await c.refresh_dynamic()
        c.user_wants_live = True
        self.assertEqual(c.live_state, "pausedFailures")
        await c.stop_recording()
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT raw_hex, valid, vrect_mv, error, validity FROM records WHERE record_type='dynamic' ORDER BY id").fetchall()
        self.assertEqual(rows[0][:3], ("01 02", 0, None))
        self.assertIn("2/20", rows[0][3])
        self.assertEqual(rows[0][4], 1)
        self.assertEqual(rows[-1][0], "")
        self.assertEqual(c.recorder.sample_count, 0)
        events, count = c.recorder.query_events(query="收集已自動暫停")
        self.assertEqual(count, 1)
        self.assertEqual(events[0]["level"], "warning")

    async def test_controller_buffer_is_bounded_but_all_recorded_events_survive(self):
        c = self.controller
        await c.start_recording(self.path)
        for index in range(1205):
            c.add_marker(f"marker {index}")
        c.on_notification(UUID_PRU_NOTIFY, b"\x80\x01\x02\x03\x04\x05\x06")
        c.on_notification(UUID_PRU_NOTIFY, b"")
        await c.close()
        self.assertEqual(len(c.log), 1000)
        self.assertEqual(c.event_count, 1209)
        self.assertEqual(c.recorder.event_count, c.event_count)
        self.assertEqual(c.recorder.query_events(kind="marker")[1], 1205)
        self.assertEqual(c.recorder.query_events(kind="alert")[0][1]["raw_hex"], "80 01 02 03 04 05 06")

    async def test_shutdown_flushes_even_if_ble_cleanup_fails(self):
        c = self.controller
        await c.start_recording(self.path)
        await c.refresh_dynamic()
        async def failed_cleanup():
            raise RuntimeError("notification cleanup failed")
        original = self.ble.disable_all_notify
        self.ble.disable_all_notify = failed_cleanup
        try:
            with self.assertRaisesRegex(RuntimeError, "notification cleanup failed"):
                await c.close()
        finally:
            self.ble.disable_all_notify = original
        self.assertFalse(c.recording)
        self.assertEqual(c.recorder.pending_count, 0)
        self.assertEqual(c.recorder.sample_count, 1)
        self.assertFalse(c.recorder._thread.is_alive())

    async def test_write_failure_keeps_recording_session_open_until_stop(self):
        c = self.controller
        await c.start_recording(self.path)
        await c.recorder.flush()
        with patch.object(c.recorder, "_write_batch", side_effect=sqlite3.OperationalError("write denied")):
            await c.refresh_dynamic()
            with self.assertRaisesRegex(RuntimeError, "write denied"):
                await c.recorder.flush()
        self.assertTrue(c.recording)
        self.assertEqual(c.recorder.sample_count, 0)
        with self.assertRaisesRegex(RuntimeError, "write denied"):
            await c.stop_recording()
        self.assertFalse(c.recording)
        self.assertIn("write denied", c.recorder.error)

    async def test_close_during_session_creation_does_not_orphan_writer(self):
        c = self.controller
        entered, release = asyncio.Event(), asyncio.Event()
        created = []
        original_create = SessionRecorder.create
        async def delayed_create(*args, **kwargs):
            entered.set()
            await release.wait()
            recorder = await original_create(*args, **kwargs)
            created.append(recorder)
            return recorder
        with patch.object(SessionRecorder, "create", side_effect=delayed_create):
            starting = asyncio.create_task(c.start_recording(self.path))
            await entered.wait()
            closing = asyncio.create_task(c.close())
            await asyncio.sleep(.01)
            release.set()
            with self.assertRaisesRegex(RuntimeError, "closed while starting"):
                await starting
            await closing
        self.assertFalse(c.recording)
        self.assertFalse(created[0]._thread.is_alive())

    async def test_command_packet_and_response_events_are_persisted_without_retries(self):
        c = self.controller
        await c.start_recording(self.path)
        await c.refresh_dynamic()
        result = await c.send("control", "DISABLE")
        c._expire_watch("control")
        await c.close()
        events, count = c.recorder.query_events(kind="command")
        self.assertEqual(result.phase, "sent")
        self.assertEqual(count, 3)
        self.assertEqual(sum(event["raw_hex"] != "" for event in events), 2)
        self.assertEqual(len([event for event in self.ble.events if isinstance(event, tuple) and event[0] == "write"]), 1)
        self.assertEqual(self.ble.max_active, 1)


if __name__ == "__main__":
    unittest.main()
