"""啟動器 — 用 qasync 橋接 Qt event loop 與 asyncio（bleak 需要 asyncio）。"""
from __future__ import annotations

import asyncio
import sys

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from app.updater import cleanup_update_artifacts
from app.windows.main_window import MainWindow


def main() -> int:
    cleanup_update_artifacts()
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
