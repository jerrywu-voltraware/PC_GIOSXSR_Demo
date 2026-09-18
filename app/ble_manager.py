"""BLE 管理（bleak 封裝） + CLI smoke test。

對照 Flutter 版 lib/bluetooth_manager.dart。重點：
- 所有對 UI 的資料都透過 pyqtSignal 派送（跨 thread 安全）
- notify callback 來自 bleak 的 asyncio thread，不可直接動 Qt widget
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.metadata
import platform
import sys
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .constants import (
    UUID_PRU_NOTIFY,
)
from .diagnostics import diagnostics_log_path, write_diagnostic, write_exception
from .ble_uuid import is_pru_service, mobile_uuid


_BLE_ENV_LOGGED = False


def _log_ble_environment_once() -> None:
    global _BLE_ENV_LOGGED
    if _BLE_ENV_LOGGED:
        return
    _BLE_ENV_LOGGED = True

    modules = [
        "bleak.backends.winrt.scanner",
        "winrt.windows.devices.bluetooth",
        "winrt.windows.devices.bluetooth.advertisement",
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        "winrt.windows.devices.enumeration",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.storage.streams",
    ]
    module_states = []
    for name in modules:
        try:
            importlib.import_module(name)
            module_states.append(f"{name}=imported")
        except Exception as exc:
            module_states.append(f"{name}=error:{exc!r}")
    module_state = ", ".join(module_states)
    try:
        bleak_version = importlib.metadata.version("bleak")
    except importlib.metadata.PackageNotFoundError:
        bleak_version = "unknown"
    write_diagnostic(
        "BLE environment: "
        f"frozen={getattr(sys, 'frozen', False)} "
        f"executable={sys.executable} "
        f"platform={platform.platform()} "
        f"python={sys.version.split()[0]} "
        f"bleak={bleak_version} "
        f"log={diagnostics_log_path()} "
        f"modules=[{module_state}]"
    )


class BleManager:
    """包裝單一 BleakClient 生命週期。"""

    def __init__(self) -> None:
        self.client: Optional[BleakClient] = None
        self.device: Optional[BLEDevice] = None
        self._notify_cb: Optional[Callable[[str, bytearray], None]] = None
        self._disconnected_cb: Optional[Callable[[], None]] = None
        self._notified_chars: set[str] = set()
        self.address = None
        self._clients = {}
        self.device_names = {}
        self._connect_tasks = set()
        self._generation = 0

    # -------- 掃描 --------
    @staticmethod
    async def scan(timeout: float = 2.0) -> list[tuple[BLEDevice, AdvertisementData]]:
        """回傳 (device, adv) list，按 RSSI 由強至弱排序。"""
        _log_ble_environment_once()
        try:
            write_diagnostic(f"BLE scan: starting timeout={timeout}.")
            discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
            # discovered: dict[str, tuple[BLEDevice, AdvertisementData]]
            items = list(discovered.values())
            items.sort(key=lambda x: x[1].rssi or -999, reverse=True)
            detail = "; ".join(
                f"{dev.address}|{adv.local_name or dev.name or '(Unknown)'}|{adv.rssi}"
                for dev, adv in items[:30]
            )
            write_diagnostic(f"BLE scan: raw_count={len(items)} items={detail}")
            return items
        except Exception as exc:
            write_exception("BLE scan failed", exc)
            raise

    # -------- 連線 --------
    async def connect(self, address: str) -> None:
        existing = self._clients.get(address)
        if existing and existing.is_connected:
            self.client = existing
            self.address = address
            return
        self.address = address
        client = BleakClient(
            address,
            disconnected_callback=self._on_disconnected,
        )
        self.client = client
        task = asyncio.current_task()
        generation = self._generation
        self._connect_tasks.add(task)
        try:
            await client.connect()
            if generation != self._generation:
                raise asyncio.CancelledError
            self._clients[address] = client
        except BaseException:
            if self.client is client:
                self.client = None
            try:
                await client.disconnect()
            except Exception:
                pass
            raise
        finally:
            self._connect_tasks.discard(task)

    def _on_disconnected(self, _client: BleakClient) -> None:
        for address, client in list(self._clients.items()):
            if client is _client:
                self._clients.pop(address, None)
        if _client is not self.client:
            return
        self._notified_chars.clear()
        if self._disconnected_cb:
            self._disconnected_cb()

    def set_disconnected_callback(self, cb: Callable[[], None]) -> None:
        self._disconnected_cb = cb

    async def disconnect(self) -> None:
        client, self.client = self.client, None
        if self.address:
            self._clients.pop(self.address, None)
        if client and client.is_connected:
            try:
                await client.disconnect()
            except Exception as e:
                print(f"disconnect error: {e}")
        self.client = None
        self._notified_chars.clear()

    def connected_devices(self):
        return [(address, self.device_names.get(address, address))
                for address, client in self._clients.items() if client.is_connected]

    async def disconnect_all(self):
        self._generation += 1
        tasks = [task for task in self._connect_tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        clients = list(self._clients.values())
        self.client = None
        self._clients.clear()
        self._notified_chars.clear()
        await asyncio.gather(*(client.disconnect() for client in clients if client.is_connected), return_exceptions=True)

    async def reconnect(self) -> None:
        if not self.address:
            raise RuntimeError("沒有可重新連線的裝置")
        await self.connect(self.address)

    async def discover(self) -> None:
        if not self.is_connected:
            raise RuntimeError("裝置未連線")
        services = self.services()  # Bleak discovers services during connect.
        write_diagnostic("BLE discovery: " + "; ".join(
            f"service={s.uuid} mobile_uuid={mobile_uuid(s.uuid)} "
            f"chars=[{','.join(str(c.uuid) for c in s.characteristics)}]"
            for s in services))

    def pru_characteristic(self, uuid):
        service = self.find_target_service()
        if service is None:
            raise RuntimeError("找不到目標 Service (fffe/bbbb)")
        for char in service.characteristics:
            if str(char.uuid).lower() == uuid.lower():
                return char
        raise RuntimeError(f"找不到特徵 …{uuid[-4:]}")

    async def read_pru(self, uuid):
        if not self.is_connected:
            raise RuntimeError("裝置未連線")
        return await asyncio.wait_for(self.client.read_gatt_char(self.pru_characteristic(uuid)), 5)

    async def write_pru(self, uuid, data):
        if not self.is_connected:
            raise RuntimeError("裝置未連線")
        await asyncio.wait_for(self.client.write_gatt_char(
            self.pru_characteristic(uuid), bytearray(data), response=True), 8)

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    # -------- Services --------
    def services(self):
        if not self.client:
            return []
        return list(self.client.services)

    def find_target_service(self):
        """Normalize WinRT UUIDs to Flutter form, then preserve first-match order."""
        for svc in self.services():
            if is_pru_service(svc.uuid):
                return svc
        return None

    # -------- Read / Write --------
    async def write(self, char_uuid: str, data: list[int] | bytes, response=True) -> None:
        if not self.client:
            raise RuntimeError("未連線")
        payload = bytearray(data)
        await self.client.write_gatt_char(char_uuid, payload, response=response)

    async def read(self, char_uuid: str) -> bytearray:
        if not self.client:
            raise RuntimeError("未連線")
        return await self.client.read_gatt_char(char_uuid)

    # -------- Notify --------
    def set_notification_callback(self, cb: Callable[[str, bytearray], None]) -> None:
        self._notify_cb = cb

    async def enable_notify(self, char_uuid: str = UUID_PRU_NOTIFY) -> None:
        if not self.client:
            raise RuntimeError("未連線")
        if char_uuid in self._notified_chars:
            return

        def _handler(sender, data: bytearray):
            # sender 可能是 int handle 或 BleakGATTCharacteristic
            uuid = getattr(sender, "uuid", str(sender))
            if self._notify_cb:
                self._notify_cb(str(uuid), bytearray(data))

        await self.client.start_notify(char_uuid, _handler)
        self._notified_chars.add(char_uuid)

    async def disable_all_notify(self) -> None:
        if not self.client or not self.client.is_connected:
            self._notified_chars.clear()
            return
        for u in list(self._notified_chars):
            try:
                await self.client.stop_notify(u)
            except Exception as e:
                print(f"stop_notify {u} error: {e}")
        self._notified_chars.clear()


# =====================================================================
# CLI smoke test
# =====================================================================
async def _cli_scan(timeout: float) -> None:
    print(f"掃描 {timeout}s ...")
    items = await BleManager.scan(timeout=timeout)
    if not items:
        print("找不到任何 BLE 裝置。請確認藍牙已開啟。")
        return
    for dev, adv in items:
        name = adv.local_name or dev.name or "(Unknown)"
        print(f"  RSSI={adv.rssi:>4}  {dev.address}  {name}")


async def _cli_connect(address: str) -> None:
    mgr = BleManager()
    print(f"連線 {address} ...")
    await mgr.connect(address)
    print("✅ 連線成功。列出 service / characteristic：")
    for svc in mgr.services():
        print(f"  [Service] {svc.uuid}")
        for c in svc.characteristics:
            props = ",".join(c.properties)
            print(f"      - {c.uuid}  ({props})")
    await mgr.disconnect()
    print("已斷線。")


def _main() -> None:
    ap = argparse.ArgumentParser(description="BleManager CLI smoke test")
    ap.add_argument("--scan", action="store_true", help="掃描 BLE 裝置")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--connect", metavar="ADDRESS", help="連線指定 MAC/UUID 並列出 services")
    args = ap.parse_args()

    if args.scan:
        asyncio.run(_cli_scan(args.timeout))
    elif args.connect:
        asyncio.run(_cli_connect(args.connect))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
