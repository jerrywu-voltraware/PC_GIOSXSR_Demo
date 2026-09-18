import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from app.ble_manager import BleManager
from app.constants import UUID_PRU_CONTROL, UUID_PRU_STATIC_READ
from app.ble_uuid import is_pru_service
from app.pru_controller import PruController


class UuidTests(unittest.TestCase):
    def test_short_and_windows_expanded_service_forms(self):
        for value in ("fffe", "bbbb", "0000FFFE", "0000bbbb",
                      "0000fffe-0000-1000-8000-00805f9b34fb",
                      "0000BBBB-0000-1000-8000-00805F9B34FB",
                      "6455e670-a146-11e2-9e96-0800200cfffe"):
            with self.subTest(value=value):
                self.assertTrue(is_pru_service(value))

    def test_unrelated_uuid_is_not_selected_by_substring(self):
        for value in ("00001800-0000-1000-8000-00805f9b34fb",
                      "0000fffe-1111-1000-8000-00805f9b34fb",
                      "fffe1234-0000-1000-8000-00805f9b34fb"):
            self.assertFalse(is_pru_service(value))


class Client:
    def __init__(self, address, disconnected_callback):
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.services = []
        self.write_gatt_char = AsyncMock()
        self.read_gatt_char = AsyncMock(return_value=bytes(20))

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected_callback(self)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_service_enters_ready_and_reads_packets(self):
        with patch("app.ble_manager.BleakClient", Client):
            ble = BleManager()
            await ble.connect("A")
            ble.client.services = [SimpleNamespace(
                uuid="0000fffe-0000-1000-8000-00805f9b34fb",
                characteristics=[SimpleNamespace(uuid=UUID_PRU_STATIC_READ),
                                 SimpleNamespace(uuid="6455e670-a146-11e2-9e96-0800200c9a6b")])]
            ble.client.start_notify = AsyncMock()
            ble.client.stop_notify = AsyncMock()
            controller = PruController(ble)
            controller.notify_delay = 0
            try:
                await controller.init()
                await asyncio.sleep(.01)
                self.assertEqual(controller.link_state, "ready")
                self.assertTrue(controller.static.valid)
                self.assertTrue(controller.dynamic.valid)
            finally:
                await controller.close()
                await ble.disconnect_all()

    async def test_shutdown_cancels_pending_connection_and_closes_local_client(self):
        started = asyncio.Event()
        instances = []
        class SlowClient(Client):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                instances.append(self)

            async def connect(self):
                self.is_connected = True
                started.set()
                await asyncio.sleep(60)
        with patch("app.ble_manager.BleakClient", SlowClient):
            ble = BleManager()
            task = asyncio.create_task(ble.connect("A"))
            await started.wait()
            await ble.disconnect_all()
            self.assertTrue(task.cancelled())
            self.assertFalse(instances[0].is_connected)
            self.assertFalse(ble.connected_devices())
            self.assertIsNone(ble.client)

    async def test_multiple_connections_retained_and_active_selection(self):
        with patch("app.ble_manager.BleakClient", Client):
            ble = BleManager()
            events = []
            ble.set_disconnected_callback(lambda: events.append("disconnected"))
            await ble.connect("A")
            a = ble.client
            await ble.connect("B")
            b = ble.client
            self.assertTrue(a.is_connected)
            self.assertEqual(len(ble.connected_devices()), 2)
            await ble.connect("A")
            self.assertIs(ble.client, a)
            await b.disconnect()
            self.assertFalse(events)
            self.assertEqual(len(ble.connected_devices()), 1)
            await a.disconnect()
            self.assertEqual(events, ["disconnected"])
            await ble.reconnect()
            self.assertTrue(ble.is_connected)
            await ble.disconnect_all()
            self.assertFalse(ble.connected_devices())

    async def test_first_target_service_and_response_write(self):
        with patch("app.ble_manager.BleakClient", Client):
            ble = BleManager()
            await ble.connect("A")
            control = SimpleNamespace(uuid=UUID_PRU_CONTROL)
            read = SimpleNamespace(uuid=UUID_PRU_STATIC_READ)
            wrong = SimpleNamespace(uuid="wrong", characteristics=[control, read])
            first = SimpleNamespace(uuid="first-fffe", characteristics=[control, read])
            second = SimpleNamespace(uuid="second-bbbb", characteristics=[])
            ble.client.services = [wrong, first, second]
            self.assertIs(ble.find_target_service(), first)
            await ble.write_pru(UUID_PRU_CONTROL, [0, 0, 0, 0, 0])
            ble.client.write_gatt_char.assert_awaited_once_with(control, bytearray(5), response=True)
            await ble.read_pru(UUID_PRU_STATIC_READ)
            ble.client.read_gatt_char.assert_awaited_once_with(read)
            first.characteristics = []
            with self.assertRaisesRegex(RuntimeError, "找不到特徵"):
                await ble.read_pru(UUID_PRU_STATIC_READ)


if __name__ == "__main__":
    unittest.main()
