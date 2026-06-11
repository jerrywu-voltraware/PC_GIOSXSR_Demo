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
    TARGET_SERVICE_UUID_SUFFIXES,
    UUID_PRU_NOTIFY,
)
from .diagnostics import diagnostics_log_path, write_diagnostic, write_exception


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
        await self.disconnect()
        self.client = BleakClient(
            address,
            disconnected_callback=self._on_disconnected,
        )
        await self.client.connect()

    def _on_disconnected(self, _client: BleakClient) -> None:
        self._notified_chars.clear()
        if self._disconnected_cb:
            self._disconnected_cb()

    def set_disconnected_callback(self, cb: Callable[[], None]) -> None:
        self._disconnected_cb = cb

    async def disconnect(self) -> None:
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
            except Exception as e:
                print(f"disconnect error: {e}")
        self.client = None
        self._notified_chars.clear()

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    # -------- Services --------
    def services(self):
        if not self.client:
            return []
        return list(self.client.services)

    def find_target_service(self):
        """尋找 UUID 結尾為 fffe 或 bbbb 的 service（同 Flutter _findTargetService）。"""
        for svc in self.services():
            uuid_l = str(svc.uuid).lower()
            for suffix in TARGET_SERVICE_UUID_SUFFIXES:
                if uuid_l.endswith(suffix):
                    return svc
        return None

    # -------- Read / Write --------
    async def write(self, char_uuid: str, data: list[int] | bytes) -> None:
        if not self.client:
            raise RuntimeError("未連線")
        payload = bytearray(data)
        await self.client.write_gatt_char(char_uuid, payload, response=True)

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
