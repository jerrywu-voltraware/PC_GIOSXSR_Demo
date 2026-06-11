"""啟動器 — 用 qasync 橋接 Qt event loop 與 asyncio（bleak 需要 asyncio）。"""
from __future__ import annotations

import asyncio
import sys

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from app.ble_manager import BleManager
from app.diagnostics import diagnostics_log_path, write_diagnostic, write_exception
from app.updater import cleanup_update_artifacts
from app.windows.main_window import MainWindow


def _prepare_windows_ble_runtime() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        from bleak.backends.winrt.util import uninitialize_sta

        uninitialize_sta()
        write_diagnostic("BLE runtime: called WinRT uninitialize_sta() at startup.")
    except Exception as exc:
        write_exception("BLE runtime preparation failed", exc)


async def _ble_scan_smoke() -> int:
    try:
        items = await BleManager.scan(timeout=5.0)
        write_diagnostic(f"BLE scan smoke: count={len(items)} log={diagnostics_log_path()}")
        return 0
    except Exception as exc:
        write_exception("BLE scan smoke failed", exc)
        return 1


def main() -> int:
    _prepare_windows_ble_runtime()
    cleanup_update_artifacts()
    if "--ble-scan-smoke" in sys.argv:
        return asyncio.run(_ble_scan_smoke())

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
