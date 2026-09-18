"""啟動器 — 用 qasync 橋接 Qt event loop 與 asyncio（bleak 需要 asyncio）。"""
from __future__ import annotations

import asyncio
import os
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from qasync import QEventLoop

from app.ble_manager import BleManager
from app.diagnostics import diagnostics_log_path, write_diagnostic, write_exception
from app.updater import cleanup_update_artifacts
from app.windows.main_window import MainWindow
from app.theme import apply_theme
from app.version import APP_VERSION


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
    if sys.platform.startswith("win"):
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GIOS.PC.GIOSXSR.Demo")
    _prepare_windows_ble_runtime()
    cleanup_update_artifacts()
    if "--ble-scan-smoke" in sys.argv:
        return asyncio.run(_ble_scan_smoke())

    ui_smoke = "--ui-smoke" in sys.argv
    if ui_smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    apply_theme(app)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(check_updates=not ui_smoke)
    window.show()
    if ui_smoke:
        assert window.stack.count() == 5
        assert not hasattr(window, "dac_page")
        assert not window.windowIcon().isNull()
        write_diagnostic(f"UI smoke: version={APP_VERSION}; 5 pages, OTA entry present, no DAC; startup OK.")
        QTimer.singleShot(250, window.close)

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
