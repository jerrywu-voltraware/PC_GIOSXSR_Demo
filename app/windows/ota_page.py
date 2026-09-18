"""Desktop OTA selection and transfer view."""
from pathlib import Path
import asyncio
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QProgressBar, QFileDialog, QMessageBox
from qasync import asyncSlot
from ..ota import OtaTransfer


class OtaPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, ble):
        super().__init__()
        self.ble = ble
        self.path = None
        self.updating = False
        self.task = None
        root = QVBoxLayout(self)
        self.back_btn = QPushButton("← 返回掃描")
        self.back_btn.clicked.connect(self.back_requested.emit)
        root.addWidget(self.back_btn)
        self.status = QLabel("OTA 服務已就緒，請選擇韌體檔案。")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.file_label = QLabel("尚未選擇 .bin")
        root.addWidget(self.file_label)
        self.pick_btn = QPushButton("選擇 .bin 韌體")
        self.pick_btn.clicked.connect(self._pick)
        root.addWidget(self.pick_btn)
        self.start_btn = QPushButton("開始更新")
        self.start_btn.clicked.connect(self._start)
        root.addWidget(self.start_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        root.addWidget(self.progress)
        root.addStretch()

    def enter_page(self):
        self.path = None
        self.file_label.setText("尚未選擇 .bin")
        self.progress.setValue(0)
        self.updating = False
        self._set_enabled(True)
        try:
            OtaTransfer(self.ble).characteristics()
            self.status.setText("OTA 服務已就緒，請選擇韌體檔案。")
        except Exception as exc:
            self.status.setText(str(exc))
            self.start_btn.setEnabled(False)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇韌體", "", "Firmware (*.bin)")
        if path:
            self.path = Path(path)
            self.file_label.setText(str(self.path))
            self.progress.setValue(0)

    def _set_enabled(self, enabled):
        for button in (self.pick_btn, self.start_btn, self.back_btn):
            button.setEnabled(enabled)

    def _progress(self, fraction, text):
        self.progress.setValue(round(fraction * 1000))
        self.status.setText(text)

    @asyncSlot()
    async def _start(self):
        if self.updating:
            return
        if self.path is None:
            self.status.setText("請先選擇 .bin 韌體檔案。")
            return
        self.updating = True
        self._set_enabled(False)
        try:
            firmware = self.path.read_bytes()
            self.task = asyncio.create_task(OtaTransfer(self.ble, self._progress).run(firmware))
            await self.task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status.setText(f"更新失敗：{exc}")
            self.updating = False
            self._set_enabled(True)

    def on_disconnected(self):
        if self.task and not self.task.done():
            self.task.cancel()
        # Mobile navigates back on any disconnect during OTA. Preserve routing,
        # but keep completion unverified until the firmware version is checked.
        self.updating = False
        self._set_enabled(True)
        self.status.setText("設備已斷線，請重新掃描並確認韌體版本。")

    def shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()

    async def close_session(self):
        self.shutdown()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None
        self.updating = False
